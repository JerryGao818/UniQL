import json
import sqlite3
import datetime
from decimal import Decimal
import math
import re
from dateutil import parser as date_parser
import os
import psycopg2

class PostgreEvaluator:
    def __init__(self, db_path, postgre_gt, postgre_pred):
        self.db_path = db_path
        self.postgre_gt = postgre_gt
        self.postgre_pred = postgre_pred
        self.host = os.getenv("UNIQL_POSTGRES_HOST", "localhost")
        self.user = os.getenv("UNIQL_POSTGRES_USER", "postgres")
        self.password = os.getenv("UNIQL_POSTGRES_PASSWORD", "<POSTGRES_PASSWORD>")
        self.port = os.getenv("UNIQL_POSTGRES_PORT", "5432")
    def normalize_row(self,row):
        """Normalize values into comparable Python types."""
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

    def postgre_query(self,query):
        """Execute a PostgreSQL query against the database inferred from db_path."""
        PG_CONFIG = {
            "host": self.host,
            "port": self.port,
            "user": self.user,
            "password": self.password,
        }
        db_name = os.path.splitext(os.path.basename(self.db_path))[0]
        conn = None
        cursor = None
        try:
            conn = psycopg2.connect(dbname=db_name, **PG_CONFIG)
            cursor = conn.cursor()
            cursor.execute(query)
            rows = cursor.fetchall()
            return rows
        except Exception as e:
            return [f"postgre Error:{e}"]
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()
        

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
        postgre_gt = self.clean_sql(self.postgre_gt)
        postgre_pred = self.clean_sql(self.postgre_pred)
        result_postgre_gt = self.postgre_query(postgre_gt)
        result_postgre_pred = self.postgre_query(postgre_pred)
        norm_gt = [self.normalize_row(row) for row in result_postgre_gt]
        norm_pred = [self.normalize_row(row) for row in result_postgre_pred]

        if len(norm_gt) != len(norm_pred):
            is_same = False
        else:
            check_order = "order by" in (self.postgre_gt.lower() + self.postgre_pred.lower())
            
            if check_order:
                # Dialect-specific evaluation step.
                is_same = True
                for r_m, r_s in zip(norm_gt, norm_pred):
                    if not self.rows_are_equal(r_m, r_s):
                        is_same = False
                        break
            else:
                # Dialect-specific evaluation step.
                pool_sqlite = list(norm_pred)
                is_same = True
                for r_m in norm_gt:
                    found = False
                    for idx, r_s in enumerate(pool_sqlite):
                        if self.rows_are_equal(r_m, r_s):
                            pool_sqlite.pop(idx)
                            found = True
                            break
                    if not found:
                        is_same = False
                        break
        return is_same,result_postgre_gt,result_postgre_pred
