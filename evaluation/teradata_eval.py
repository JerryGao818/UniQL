import teradatasql
import json
import datetime
from decimal import Decimal
import math
import re
from dateutil import parser as date_parser
import os


class TeradataEvaluator:
    def __init__(self, db_path, teradata_gt, teradata_pred):
        self.db_path = db_path
        self.teradata_gt = teradata_gt
        self.teradata_pred = teradata_pred
        self.host = "192.168.92.130"
        self.user = "dbc"
        self.password = "dbc"

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

    def teradata_query(self, query):
        db_name = os.path.splitext(os.path.basename(self.db_path))[0]
        connection = None
        cursor = None
        try:
            connection = teradatasql.connect(
                host=self.host,
                user=self.user,
                password=self.password,
                tmode="ANSI",
            )
            cursor = connection.cursor()
            cursor.execute(f"DATABASE {db_name.lower()}")
            cursor.execute(query)
            results = cursor.fetchall()
            return results
        except Exception as e:
            return [f"Teradata Error: {str(e)}"]
        finally:
            try:
                if cursor:
                    cursor.close()
            except:
                pass
            try:
                if connection:
                    connection.close()
            except:
                pass

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

    def check_result_same(self):
        teradata_gt = self.clean_sql(self.teradata_gt)
        teradata_pred = self.clean_sql(self.teradata_pred)

        result_gt = self.teradata_query(teradata_gt)
        result_pred = self.teradata_query(teradata_pred)

        if isinstance(result_gt, list) and len(result_gt) == 1 and str(result_gt[0]).startswith("Teradata Error"):
            return False, result_gt, result_pred
        if isinstance(result_pred, list) and len(result_pred) == 1 and str(result_pred[0]).startswith("Teradata Error"):
            return False, result_gt, result_pred

        norm_gt = [self.normalize_row(row) for row in result_gt]
        norm_pred = [self.normalize_row(row) for row in result_pred]

        if len(norm_gt) != len(norm_pred):
            is_same = False
        else:
            check_order = "order by" in (self.teradata_gt.lower() + self.teradata_pred.lower())
            if check_order:
                is_same = True
                for r_m, r_s in zip(norm_gt, norm_pred):
                    if not self.rows_are_equal(r_m, r_s):
                        is_same = False
                        break
            else:
                pool_pred = list(norm_pred)
                is_same = True
                for r_m in norm_gt:
                    found = False
                    for idx, r_s in enumerate(pool_pred):
                        if self.rows_are_equal(r_m, r_s):
                            pool_pred.pop(idx)
                            found = True
                            break
                    if not found:
                        is_same = False
                        break

        return is_same, result_gt, result_pred
