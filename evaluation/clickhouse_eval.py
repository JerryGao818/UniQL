import json
import sqlite3
import datetime
from decimal import Decimal
import math
import re
from dateutil import parser as date_parser
import os
import subprocess
import time
import clickhouse_connect

class ClickHouseEvaluator:
    def __init__(self, db_path, ch_gt, ch_pred):
        self.db_path = db_path
        self.ch_gt = ch_gt
        self.ch_pred = ch_pred
        self.host = 'localhost'
        self.user = 'default'
        self.password = ''
        self.port = 8124

    def is_clickhouse_alive(self, db_name):
        try:
            ch_client = clickhouse_connect.get_client(
                host=self.host,
                port=self.port,
                username=self.user,
                password=self.password,
                database=db_name
            )
            ch_client.query("SELECT 1")
            return True
        except Exception:
            return False
        finally:
            try:
                ch_client.close()
            except Exception:
                pass

    def restart_clickhouse(self, db_name):
        restart_cmd = os.getenv("CLICKHOUSE_EVAL_RESTART_CMD")
        container_name = os.getenv("CLICKHOUSE_EVAL_CONTAINER", "clickhouse-server")

        try:
            if restart_cmd:
                subprocess.run(restart_cmd, shell=True, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                subprocess.run(["docker", "restart", container_name], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            return False

        for _ in range(30):
            if self.is_clickhouse_alive(db_name):
                return True
            time.sleep(1)
        return False

    def ensure_clickhouse_alive(self, db_name):
        if self.is_clickhouse_alive(db_name):
            return True
        return self.restart_clickhouse(db_name)

    def normalize_row(self,row):
        """
        """
        new_row = []
        for val in row:
            if isinstance(val, (int, float, Decimal)):
                try:
                    val = round(float(val), 3)
                except:
                    pass
            elif isinstance(val, (datetime.date, datetime.datetime, datetime.time, datetime.timedelta)):
                val = str(val)
            elif isinstance(val, bytes):
                try:
                    val = val.decode('utf-8')
                except:
                    pass
            elif isinstance(val, (datetime.date, datetime.datetime)):
                if isinstance(val, datetime.datetime):
                    val = val.strftime('%Y-%m-%d %H:%M:%S')
                val = str(val)
            elif isinstance(val, str):
                val = val.strip()
                time_pattern = r'^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?$'
                if re.match(time_pattern, val):
                    try:
                        dt = date_parser.parse(val)
                        val = dt.strftime('%Y-%m-%d %H:%M:%S')
                    except:
                        pass
            new_row.append(val)
        return tuple(new_row)

    def clickhouse_query(self,query):
        """
        """
        db_name = os.path.splitext(os.path.basename(self.db_path))[0]
        self.ensure_clickhouse_alive(db_name)
        try:
            ch_client = clickhouse_connect.get_client(
                host=self.host,
                port=self.port,
                username=self.user,
                password=self.password,
                database=db_name
            )
            results = ch_client.query(query)      
            return results.result_rows
                
        except Exception as e:
            if not self.is_clickhouse_alive(db_name):
                self.restart_clickhouse(db_name)
            return [f"clickhouse Error: {e}"]
    
        
    def rows_are_equal(self,row_a, row_b, tolerance=1e-3):
        """Compare normalized query results."""
        if len(row_a) != len(row_b): return False
        for val_a, val_b in zip(row_a, row_b):
            if isinstance(val_a, float) and isinstance(val_b, float):
                if math.isnan(val_a) and math.isnan(val_b): continue
                if abs(val_a - val_b) > tolerance: return False
            elif val_a is None or val_b is None:
                if val_a != val_b: return False
            else:
                if val_a != val_b: return False
        return True
    def clean_sql(self,sql):
        sql = sql
        return sql
    def check_result_same(self):
        ch_gt = self.clean_sql(self.ch_gt)
        ch_pred = self.clean_sql(self.ch_pred)
        result_ch_gt = self.clickhouse_query(ch_gt)
        result_ch_pred = self.clickhouse_query(ch_pred)
        norm_ch_gt = [self.normalize_row(row) for row in result_ch_gt]
        norm_ch_pred = [self.normalize_row(row) for row in result_ch_pred]

        if len(norm_ch_gt) != len(norm_ch_pred):
            is_same = False
        else:
            check_order = "order by" in (self.ch_gt.lower() + self.ch_pred.lower())
            
            if check_order:
                # Dialect-specific evaluation step.
                is_same = True
                for r_m, r_s in zip(norm_ch_gt, norm_ch_pred):
                    if not self.rows_are_equal(r_m, r_s):
                        is_same = False
                        break
            else:
                # Dialect-specific evaluation step.
                pool_sqlite = list(norm_ch_pred)
                is_same = True
                for r_m in norm_ch_gt:
                    found = False
                    for idx, r_s in enumerate(pool_sqlite):
                        if self.rows_are_equal(r_m, r_s):
                            pool_sqlite.pop(idx)
                            found = True
                            break
                    if not found:
                        is_same = False
                        break
        return is_same,result_ch_gt,result_ch_pred
