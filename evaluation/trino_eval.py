import datetime
import json
import math
import os
import re
from decimal import Decimal

import requests

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


class TrinoEvaluator:
    def __init__(self, db_path, trino_gt, trino_pred):
        self.db_path = db_path
        self.trino_gt = trino_gt
        self.trino_pred = trino_pred
        self.host = os.getenv("TRINO_HOST", "localhost")
        self.port = int(os.getenv("TRINO_PORT", "8080"))
        self.user = os.getenv("TRINO_USER", "trino")
        self.catalog = os.getenv("TRINO_CATALOG", "hive")

    def trino_query(self, query):
        db_name = os.path.splitext(os.path.basename(self.db_path))[0]
        url = f"http://{self.host}:{self.port}/v1/statement"
        headers = {
            "X-Trino-User": self.user,
            "X-Trino-Catalog": self.catalog,
            "X-Trino-Schema": db_name.lower(),
        }
        rows = []
        try:
            response = requests.post(url, headers=headers, data=query, timeout=120)
            if response.status_code >= 400:
                return [f"trino Error: HTTP {response.status_code}: {response.text}"]
            body = response.json()
            rows.extend(body.get("data", []))
            next_uri = body.get("nextUri")
            while next_uri:
                next_response = requests.get(next_uri, timeout=120)
                next_body = next_response.json()
                rows.extend(next_body.get("data", []))
                next_uri = next_body.get("nextUri")
                if next_body.get("error"):
                    return [f"trino Error: {json.dumps(next_body['error'], ensure_ascii=False)}"]
            if body.get("error"):
                return [f"trino Error: {json.dumps(body['error'], ensure_ascii=False)}"]
            return [tuple(row) for row in rows]
        except Exception as exc:
            return [f"trino Error: {exc}"]

    def check_result_same(self):
        trino_gt = clean_sql(self.trino_gt)
        trino_pred = clean_sql(self.trino_pred)
        result_gt = self.trino_query(trino_gt)
        result_pred = self.trino_query(trino_pred)

        if isinstance(result_gt, list) and len(result_gt) == 1 and str(result_gt[0]).startswith("trino Error"):
            return False, result_gt, result_pred
        if isinstance(result_pred, list) and len(result_pred) == 1 and str(result_pred[0]).startswith("trino Error"):
            return False, result_gt, result_pred

        return compare_results(result_gt, result_pred, trino_gt, trino_pred), result_gt, result_pred
