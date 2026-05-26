import datetime
import math
import os
import re
from decimal import Decimal

import requests

from dateutil import parser as date_parser


RESERVED_KEYWORDS = {
    "order",
    "group",
    "user",
    "date",
    "timestamp",
    "interval",
    "from",
    "to",
    "select",
    "table",
}


def clean_identifier(name):
    clean = re.sub(r"[^a-zA-Z0-9_]", "_", str(name)).lower()
    clean = re.sub(r"_+", "_", clean).strip("_")
    if not clean:
        clean = "col_unknown"
    if clean[0].isdigit():
        clean = f"col_{clean}"
    if clean in RESERVED_KEYWORDS:
        clean = f"{clean}_col"
    return clean


def clean_db_name(db_name):
    return clean_identifier(db_name)


def clean_table_name(table_name, db_name=None):
    if db_name:
        return f"{clean_db_name(db_name)}/{clean_identifier(table_name)}"
    return clean_identifier(table_name)


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


class DrillEvaluator:
    def __init__(self, db_path, drill_gt, drill_pred):
        self.db_path = db_path
        self.drill_gt = drill_gt
        self.drill_pred = drill_pred
        self.query_url = os.getenv("DRILL_QUERY_URL", "http://127.0.0.1:8047/query.json")
        self.auto_qualify = os.getenv("DRILL_AUTO_QUALIFY", "1") != "0"
        self.timeout = float(os.getenv("DRILL_QUERY_TIMEOUT", "180"))

    def _qualify_tables(self, query):
        if not self.auto_qualify:
            return query
        db_name = clean_db_name(os.path.splitext(os.path.basename(self.db_path))[0])
        alias_keywords = {
            "on", "where", "join", "left", "right", "inner", "outer", "full",
            "cross", "group", "order", "limit", "having", "union", "except",
            "intersect", "qualify", "window",
        }

        def replace(match):
            keyword = match.group(1)
            raw_table = match.group(2).strip()
            alias = match.group(3)
            if raw_table.startswith("("):
                return match.group(0)

            table_ref = raw_table
            if table_ref and table_ref[0] in {'`', '"'} and table_ref[-1:] == table_ref[0]:
                table_ref = table_ref[1:-1]

            if table_ref.startswith("dfs.bird."):
                return match.group(0)

            if "/" in table_ref:
                db_part, table = table_ref.split("/", 1)
                table_alias = alias or clean_identifier(table)
                path = clean_table_name(table, db_part)
                return f"{keyword} dfs.bird.`{path}` AS {table_alias}"

            if "." in table_ref:
                db_part, table = table_ref.split(".", 1)
                table_alias = alias or clean_identifier(table)
                path = clean_table_name(table, db_part)
                return f"{keyword} dfs.bird.`{path}` AS {table_alias}"

            table = table_ref.strip('`"')
            table_alias = alias or clean_identifier(table)
            path = clean_table_name(table, db_name)
            return f"{keyword} dfs.bird.`{path}` AS {table_alias}"

        alias_pattern = (
            r"\b(FROM|JOIN)\s+([^\s,()]+)"
            r"(?:\s+(?:AS\s+)?(?!"
            + "|".join(alias_keywords)
            + r"\b)([A-Za-z_][\w]*))?"
        )
        return re.sub(alias_pattern, replace, query, flags=re.IGNORECASE)

    def drill_query(self, query):
        payload = {
            "queryType": "SQL",
            "query": self._qualify_tables(query),
            "autoLimit": 100000,
        }
        try:
            response = requests.post(self.query_url, json=payload, timeout=self.timeout)
            if response.status_code != 200:
                return [f"drill Error: HTTP {response.status_code}: {response.text}"]
            body = response.json()
            if body.get("queryState") != "COMPLETED":
                return [f"drill Error: {body.get('errorMessage', body)}"]
            rows = body.get("rows", [])
            if not rows:
                return []
            if isinstance(rows[0], dict):
                columns = list(rows[0].keys())
                return [tuple(row.get(column) for column in columns) for row in rows]
            return rows
        except Exception as exc:
            return [f"drill Error: {exc}"]

    def check_result_same(self):
        drill_gt = clean_sql(self.drill_gt)
        drill_pred = clean_sql(self.drill_pred)
        result_gt = self.drill_query(drill_gt)
        result_pred = self.drill_query(drill_pred)

        if isinstance(result_gt, list) and len(result_gt) == 1 and str(result_gt[0]).startswith("drill Error"):
            return False, result_gt, result_pred
        if isinstance(result_pred, list) and len(result_pred) == 1 and str(result_pred[0]).startswith("drill Error"):
            return False, result_gt, result_pred

        return compare_results(result_gt, result_pred, drill_gt, drill_pred), result_gt, result_pred
