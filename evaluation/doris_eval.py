import datetime
import math
import os
import re
from decimal import Decimal

import pymysql

from dateutil import parser as date_parser


def normalize_row(row):
    normalized = []
    for val in row:
        if isinstance(val, str) and val.strip() in {r"\N", "NULL", "null"}:
            val = None
        if val is None:
            normalized.append(None)
            continue
        if isinstance(val, (int, float, Decimal)):
            try:
                normalized.append(round(float(val), 3))
                continue
            except Exception:
                pass
        if isinstance(val, (datetime.date, datetime.datetime, datetime.time, datetime.timedelta)):
            val = str(val)
        if isinstance(val, bytes):
            try:
                val = val.decode("utf-8")
            except Exception:
                pass
        if isinstance(val, str):
            val = val.strip()
            time_pattern = r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?$"
            if re.match(time_pattern, val):
                try:
                    dt = date_parser.parse(val)
                    val = dt.strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    pass
        normalized.append(val)
    return tuple(normalized)


def rows_are_equal(row_a, row_b, tolerance=1e-3):
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


def clean_sql(sql):
    cleaned = (sql or "").strip()
    if cleaned.endswith(";"):
        cleaned = cleaned[:-1].rstrip()
    return cleaned


def compare_results(gt_rows, pred_rows, gt_sql, pred_sql):
    norm_gt = [normalize_row(row) for row in gt_rows]
    norm_pred = [normalize_row(row) for row in pred_rows]
    if len(norm_gt) != len(norm_pred):
        return False

    check_order = "order by" in ((gt_sql or "").lower() + (pred_sql or "").lower())
    if check_order:
        return all(rows_are_equal(row_gt, row_pred) for row_gt, row_pred in zip(norm_gt, norm_pred))

    pool_pred = list(norm_pred)
    for row_gt in norm_gt:
        found = False
        for idx, row_pred in enumerate(pool_pred):
            if rows_are_equal(row_gt, row_pred):
                pool_pred.pop(idx)
                found = True
                break
        if not found:
            return False
    return True


class DorisEvaluator:
    def __init__(self, db_path, doris_gt, doris_pred):
        self.db_path = db_path
        self.doris_gt = doris_gt
        self.doris_pred = doris_pred
        self.host = os.getenv("DORIS_HOST", "localhost")
        self.user = os.getenv("DORIS_USER", "root")
        self.password = os.getenv("DORIS_PASSWORD", "")
        self.port = int(os.getenv("DORIS_PORT", "9030"))

    def doris_query(self, query):
        conn = None
        cursor = None
        try:
            db_name = os.path.splitext(os.path.basename(self.db_path))[0]
            conn = pymysql.connect(
                host=self.host,
                user=self.user,
                password=self.password,
                port=self.port,
                database=db_name,
                init_command="SET SESSION sql_mode='NO_ENGINE_SUBSTITUTION'",
            )
            cursor = conn.cursor()
            cursor.execute(query)
            return cursor.fetchall()
        except Exception as exc:
            return [f"doris Error: {exc}"]
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    def check_result_same(self):
        doris_gt = clean_sql(self.doris_gt)
        doris_pred = clean_sql(self.doris_pred)
        result_gt = self.doris_query(doris_gt)
        result_pred = self.doris_query(doris_pred)

        if isinstance(result_gt, list) and len(result_gt) == 1 and str(result_gt[0]).startswith("doris Error"):
            return False, result_gt, result_pred
        if isinstance(result_pred, list) and len(result_pred) == 1 and str(result_pred[0]).startswith("doris Error"):
            return False, result_gt, result_pred

        return compare_results(result_gt, result_pred, doris_gt, doris_pred), result_gt, result_pred
