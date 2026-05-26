import requests
import json
import sqlite3
import datetime
from decimal import Decimal
import math
import re
from dateutil import parser as date_parser
import os


DRUID_SQL_URL = "http://localhost:8888/druid/v2/sql"


class DruidEvaluator:
    def __init__(self, db_path, druid_gt, druid_pred):
        self.db_path = db_path
        self.druid_gt = druid_gt
        self.druid_pred = druid_pred
        self.sql_url = DRUID_SQL_URL
        self.timeout = 60

    def normalize_row(self, row):
        """Normalize values into comparable Python types."""
        if isinstance(row, dict):
            # Dialect-specific evaluation step.
            vals = list(row.values())
        else:
            vals = list(row)

        new_row = []
        for val in vals:
            if val is None:
                new_row.append(None)
                continue
            try:
                if isinstance(val, (int, float, Decimal)):
                    new_row.append(round(float(val), 3))
                    continue
            except:
                pass

            val_str = str(val).strip()
            # Dialect-specific evaluation step.
            time_pattern = r'^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z)?$'
            if re.match(time_pattern, val_str):
                try:
                    dt = date_parser.parse(val_str)
                    new_row.append(dt.strftime('%Y-%m-%d %H:%M:%S'))
                    continue
                except:
                    pass
            new_row.append(val_str)
        return tuple(new_row)

    def druid_query(self, query):
        """
        """
        payload = {
            "query": query,
            "context": {
                "maxSubqueryBytes": "auto",
                "useApproximateCountDistinct": False
            }
        }
        try:
            response = requests.post(
                self.sql_url,
                json=payload,
                timeout=self.timeout
            )
            if response.status_code == 200:
                return response.json()
            else:
                return [f"Druid Error: HTTP {response.status_code}: {response.text[:500]}"]
        except Exception as e:
            return [f"Druid Error: {str(e)}"]

    def rows_are_equal(self, row_a, row_b, tolerance=1e-3):
        """Compare normalized query results."""
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
        druid_gt = self.clean_sql(self.druid_gt)
        druid_pred = self.clean_sql(self.druid_pred)

        result_gt = self.druid_query(druid_gt)
        result_pred = self.druid_query(druid_pred)

        # Dialect-specific evaluation step.
        if isinstance(result_gt, list) and len(result_gt) == 1 and isinstance(result_gt[0], str) and result_gt[0].startswith("Druid Error"):
            return False, result_gt, result_pred
        if isinstance(result_pred, list) and len(result_pred) == 1 and isinstance(result_pred[0], str) and result_pred[0].startswith("Druid Error"):
            return False, result_gt, result_pred

        norm_gt = [self.normalize_row(row) for row in result_gt]
        norm_pred = [self.normalize_row(row) for row in result_pred]

        if len(norm_gt) != len(norm_pred):
            is_same = False
        else:
            check_order = "order by" in (self.druid_gt.lower() + self.druid_pred.lower())

            if check_order:
                # Dialect-specific evaluation step.
                is_same = True
                for r_gt, r_pred in zip(norm_gt, norm_pred):
                    if not self.rows_are_equal(r_gt, r_pred):
                        is_same = False
                        break
            else:
                # Dialect-specific evaluation step.
                pool_pred = list(norm_pred)
                is_same = True
                for r_gt in norm_gt:
                    found = False
                    for idx, r_pred in enumerate(pool_pred):
                        if self.rows_are_equal(r_gt, r_pred):
                            pool_pred.pop(idx)
                            found = True
                            break
                    if not found:
                        is_same = False
                        break

        return is_same, result_gt, result_pred
