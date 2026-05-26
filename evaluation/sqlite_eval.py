import json
import sqlite3
import datetime
from decimal import Decimal
import math
import re
from dateutil import parser as date_parser
import multiprocessing as mp
import sys
from func_timeout import func_timeout, FunctionTimedOut

class SQLiteEvaluator:
    def __init__(self, db_path,sqlite_gt,sqlite_pred):
        self.db_path = db_path
        self.sqlite_gt = sqlite_gt
        self.sqlite_pred = sqlite_pred

    def normalize_row(self, row):
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

    def execute_sqlite_query(self, sql_content):
        conn = None
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(sql_content)
            results = cursor.fetchall()
            return results
        except Exception as e:
            print(f"SQLite Error: {e}")
            return [f"SQLite Error: {e}"]
        finally:
            if conn: conn.close()

    def rows_are_equal(self, row_a, row_b, tolerance=1e-3):
        if len(row_a) != len(row_b):
            return False
        for val_a, val_b in zip(row_a, row_b):
            if isinstance(val_a, float) and isinstance(val_b, float):
                if math.isnan(val_a) and math.isnan(val_b):
                    continue
                if abs(val_a - val_b) > tolerance:
                    return False
            elif val_a is None or val_b is None:
                if val_a != val_b:
                    return False
            else:
                if val_a != val_b:
                    return False
        return True

    def _clean_sql(self,sql:str):
        sql = re.sub(r'--.*?$', '', sql, flags=re.MULTILINE)
        sql_cleaned = sql.replace('\\n', ' ').replace('\n', ' ').replace('\t', ' ')
        sql_cleaned = re.sub(r'\s+', ' ', sql_cleaned)
        # Dialect-specific evaluation step.
        sql_cleaned = sql_cleaned.rstrip(';').strip()
        return sql_cleaned

    def check_result_same(self):

        sqlite_gt = self._clean_sql(self.sqlite_gt)
        sqlite_pred = self._clean_sql(self.sqlite_pred)
        result_sqlite_gt = self.execute_sqlite_query(sqlite_gt)
        result_sqlite_pred = self.execute_sqlite_query(sqlite_pred)

        norm_gt = [self.normalize_row(r) for r in result_sqlite_gt]
        norm_pred = [self.normalize_row(r) for r in result_sqlite_pred]

        if len(norm_gt) != len(norm_pred):
            return False, result_sqlite_gt, result_sqlite_pred

        # Dialect-specific evaluation step.
        check_order = "order by" in (self.sqlite_gt.lower() + self.sqlite_pred.lower())

        if check_order:
            is_same = True
            for r_gt, r_pd in zip(norm_gt, norm_pred):
                if not self.rows_are_equal(r_gt, r_pd):
                    is_same = False
                    break
        else:
            pool = list(norm_pred)
            is_same = True
            for r_gt in norm_gt:
                found = False
                for idx, r_pd in enumerate(pool):
                    if self.rows_are_equal(r_gt, r_pd):
                        pool.pop(idx)
                        found = True
                        break
                if not found:
                    is_same = False
                    break

        return is_same, result_sqlite_gt, result_sqlite_pred
