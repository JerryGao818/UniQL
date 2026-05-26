import duckdb
import json
import sqlite3
import datetime
from decimal import Decimal
import math
import re
from dateutil import parser as date_parser
import os


class DuckDBEvaluator:
    def __init__(self, db_path, duckdb_gt, duckdb_pred):
        self.db_path = db_path
        self.duckdb_gt = duckdb_gt
        self.duckdb_pred = duckdb_pred
        self.duckdb_path = os.getenv("UNIQL_DUCKDB_PATH", "<DUCKDB_DATABASE_PATH>")
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
    
    def duckdb_query(self, query):
        """Execute a query in DuckDB."""
        con = duckdb.connect(self.duckdb_path, read_only=True)
        db_name = os.path.splitext(os.path.basename(self.db_path))[0]
        try:
            # Dialect-specific evaluation step.
            con.execute(f"SET schema = '{db_name}'")
            result = con.execute(query).fetchall()
            return result
        except Exception as e:
            return [f"duckdb Error: {e}"]
        
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
        duckdb_gt = self.clean_sql(self.duckdb_gt)
        duckdb_pred = self.clean_sql(self.duckdb_pred)
        result_duckdb_gt = self.duckdb_query(duckdb_gt)
        result_duckdb_pred = self.duckdb_query(duckdb_pred)
        norm_duckdb_gt = [self.normalize_row(row) for row in result_duckdb_gt]
        norm_duckdb_pred = [self.normalize_row(row) for row in result_duckdb_pred]

        if len(norm_duckdb_gt) != len(norm_duckdb_pred):
            is_same = False
        else:
            check_order = "order by" in (self.duckdb_gt.lower() + self.duckdb_pred.lower())

            if check_order:
                # Dialect-specific evaluation step.
                is_same = True
                for r_m, r_s in zip(norm_duckdb_gt, norm_duckdb_pred):
                    if not self.rows_are_equal(r_m, r_s):
                        is_same = False
                        break
            else:
                # Dialect-specific evaluation step.
                pool_sqlite = list(norm_duckdb_pred)
                is_same = True
                for r_m in norm_duckdb_gt:
                    found = False
                    for idx, r_s in enumerate(pool_sqlite):
                        if self.rows_are_equal(r_m, r_s):
                            pool_sqlite.pop(idx)
                            found = True
                            break
                    if not found:
                        is_same = False
                        break
        return is_same,result_duckdb_gt,result_duckdb_pred

