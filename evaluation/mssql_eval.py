import datetime
import math
import os
import re
from decimal import Decimal

import pymssql
from dateutil import parser as date_parser


class MSSQLEvaluator:
    def __init__(self, db_path, mssql_gt, mssql_pred):
        self.db_path = db_path
        self.mssql_gt = mssql_gt
        self.mssql_pred = mssql_pred
        self.host = os.environ.get("MSSQL_HOST", "localhost")
        self.user = os.environ.get("MSSQL_USER", "SA")
        self.password = os.environ.get("MSSQL_PASSWORD", "<MSSQL_PASSWORD>")
        self.port = int(os.environ.get("MSSQL_PORT", "1433"))
        self.charset = os.environ.get("MSSQL_CHARSET", "utf8")

    def normalize_row(self, row):
        new_row = []
        for val in row:
            if isinstance(val, (int, float, Decimal)):
                try:
                    val = round(float(val), 3)
                except Exception:
                    pass
            elif isinstance(val, (datetime.date, datetime.datetime, datetime.time, datetime.timedelta)):
                if isinstance(val, datetime.datetime):
                    val = val.strftime('%Y-%m-%d %H:%M:%S')
                else:
                    val = str(val)
            elif isinstance(val, bytes):
                try:
                    val = val.decode('utf-8')
                except Exception:
                    pass
            elif isinstance(val, str):
                val = val.strip()
                time_pattern = r'^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?$'
                if re.match(time_pattern, val):
                    try:
                        dt = date_parser.parse(val)
                        val = dt.strftime('%Y-%m-%d %H:%M:%S')
                    except Exception:
                        pass
            new_row.append(val)
        return tuple(new_row)

    def mssql_query(self, query):
        connection = None
        cursor = None
        db_name = os.path.splitext(os.path.basename(self.db_path))[0]
        try:
            connection = pymssql.connect(
                server=self.host,
                user=self.user,
                password=self.password,
                database=db_name,
                port=self.port,
                charset=self.charset,
                as_dict=False,
            )
            cursor = connection.cursor()
            cursor.execute(query)
            return cursor.fetchall()
        except Exception as e:
            raise RuntimeError(f"mssql Error: {e}")
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
        sql = re.sub(r'--.*?$', '', sql, flags=re.MULTILINE)
        sql = sql.replace('\\n', ' ').replace('\n', ' ').replace('\t', ' ')
        sql = re.sub(r'\s+', ' ', sql)
        return sql.rstrip(';').strip()

    def check_result_same(self):
        mssql_gt = self.clean_sql(self.mssql_gt)
        mssql_pred = self.clean_sql(self.mssql_pred)
        result_mssql_gt = self.mssql_query(mssql_gt)
        result_mssql_pred = self.mssql_query(mssql_pred)
        norm_gt = [self.normalize_row(row) for row in result_mssql_gt]
        norm_pred = [self.normalize_row(row) for row in result_mssql_pred]

        if len(norm_gt) != len(norm_pred):
            is_same = False
        else:
            check_order = "order by" in (self.mssql_gt.lower() + self.mssql_pred.lower())

            if check_order:
                is_same = True
                for row_gt, row_pred in zip(norm_gt, norm_pred):
                    if not self.rows_are_equal(row_gt, row_pred):
                        is_same = False
                        break
            else:
                pool_pred = list(norm_pred)
                is_same = True
                for row_gt in norm_gt:
                    found = False
                    for idx, row_pred in enumerate(pool_pred):
                        if self.rows_are_equal(row_gt, row_pred):
                            pool_pred.pop(idx)
                            found = True
                            break
                    if not found:
                        is_same = False
                        break
        return is_same, result_mssql_gt, result_mssql_pred
