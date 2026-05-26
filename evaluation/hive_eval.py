from pyhive import hive
import math
import os
import re
import time
from dateutil import parser as date_parser


class HiveEvaluator:
    def __init__(self, db_path, hive_gt, hive_pred):
        self.db_path = db_path
        self.hive_gt = hive_gt
        self.hive_pred = hive_pred
        self.host = 'localhost'
        self.user = 'hive'
        self.port = 10000

    def is_retryable_hive_error(self, error):
        error_text = str(error).lower()
        retryable_patterns = [
            "tsocket read 0 bytes",
        ]
        return any(pattern in error_text for pattern in retryable_patterns)

    def normalize_row(self, row):
        new_row = []
        for val in row:
            if isinstance(val, str) and (val.strip() == r'\N' or val.strip() == 'NULL'):
                val = None

            if val is None:
                new_row.append(None)
                continue
            try:
                if '.' in str(val):
                    new_row.append(round(float(val), 3))
                    continue
                else:
                    new_row.append(float(int(val)))
                    continue
            except Exception:
                pass
            val_str = str(val).strip()
            time_pattern = r'^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?$'
            if re.match(time_pattern, val_str):
                try:
                    dt = date_parser.parse(val_str)
                    new_row.append(dt.strftime('%Y-%m-%d %H:%M:%S'))
                    continue
                except Exception:
                    pass
            new_row.append(val_str)
        return tuple(new_row)

    def hive_query(self, query):
        attempt = 1
        while True:
            connection = None
            cursor = None
            try:
                connection = hive.Connection(
                    host=self.host,
                    port=self.port,
                    username=self.user,
                    database=os.path.splitext(os.path.basename(self.db_path))[0],
                )

                cursor = connection.cursor()
                cursor.execute(query)
                results = cursor.fetchall()
                return results

            except Exception as e:
                if self.is_retryable_hive_error(e):
                    wait_seconds = min(2 ** attempt, 30)
                    print(f"Hive transient error: {e}. Retrying in {wait_seconds}s... (attempt {attempt})")
                    time.sleep(wait_seconds)
                    attempt += 1
                    continue
                return [f"hive Error: {e}"]
            finally:
                if cursor:
                    cursor.close()
                if connection:
                    connection.close()

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

    def clean_sql(self, sql):
        cleaned = sql.strip()
        if cleaned.endswith(";"):
            cleaned = cleaned[:-1].rstrip()
        return cleaned

    def is_hive_error(self, result):
        return (
            isinstance(result, list)
            and len(result) == 1
            and str(result[0]).startswith("hive Error")
        )

    def check_result_same(self):
        hive_gt = self.clean_sql(self.hive_gt)
        hive_pred = self.clean_sql(self.hive_pred)
        result_hive_gt = self.hive_query(hive_gt)
        result_hive_pred = self.hive_query(hive_pred)
        if self.is_hive_error(result_hive_gt):
            return False, result_hive_gt, result_hive_pred
        if self.is_hive_error(result_hive_pred):
            return False, result_hive_gt, result_hive_pred

        norm_hive_gt = [self.normalize_row(row) for row in result_hive_gt]
        norm_hive_pred = [self.normalize_row(row) for row in result_hive_pred]

        if len(norm_hive_gt) != len(norm_hive_pred):
            is_same = False
        else:
            check_order = "order by" in (self.hive_gt.lower() + self.hive_pred.lower())

            if check_order:
                is_same = True
                for r_m, r_s in zip(norm_hive_gt, norm_hive_pred):
                    if not self.rows_are_equal(r_m, r_s):
                        is_same = False
                        break
            else:
                pool_sqlite = list(norm_hive_pred)
                is_same = True
                for r_m in norm_hive_gt:
                    found = False
                    for idx, r_s in enumerate(pool_sqlite):
                        if self.rows_are_equal(r_m, r_s):
                            pool_sqlite.pop(idx)
                            found = True
                            break
                    if not found:
                        is_same = False
                        break
        return is_same, result_hive_gt, result_hive_pred
