import json
import re
import math
import datetime
from decimal import Decimal
import os

_NUMERIC_RE = re.compile(r"^[+-]value\d+(value:\.\d+)value(value:[eE][+-]value\d+)value$")
_DATETIME_RE = re.compile(
    r"^(valueP<d>\d{4}-\d{2}-\d{2})"  # date
    r"(value:[ T](valueP<t>\d{2}:\d{2}:\d{2})(value:\.\d+)value)value"  # optional time with optional micros
    r"(value:Z|[+-]\d{2}:\d{2})value$"  # optional timezone
)


def _normalize_datetime_string(s: str) -> str:
    """Normalize common datetime string shapes across drivers.

    - 'YYYY-MM-DD' stays as date
    - 'YYYY-MM-DD HH:MM:SS.xxx' -> 'YYYY-MM-DD HH:MM:SS'
    - 'YYYY-MM-DDTHH:MM:SS' -> 'YYYY-MM-DD HH:MM:SS'
    """
    m = _DATETIME_RE.match(s)
    if not m:
        return s
    date_part = m.group("d")
    time_part = m.group("t")
    return f"{date_part} {time_part}" if time_part else date_part


def _to_number_if_possible(s: str):
    """Best-effort numeric coercion for numeric-looking strings.

    Used to reduce false mismatches where one DB returns numbers as strings.
    """
    if not _NUMERIC_RE.match(s):
        return None
    try:
        d = Decimal(s)
    except Exception:
        return None
    try:
        f = float(d)
    except Exception:
        return None
    if math.isnan(f) or math.isinf(f):
        return f
    if abs(f - round(f)) < 1e-12:
        return int(round(f))
    return f


def normalize_value(
    val,
    *,
    float_round: int = 3,
    coerce_numeric_strings: bool = True,
    coerce_bool: bool = True,
):
    """Normalize a scalar value into a stable, comparable, hashable form."""
    if val is None:
        return None

    if coerce_bool and isinstance(val, bool):
        return int(val)

    if isinstance(val, memoryview):
        val = bytes(val)
    if isinstance(val, (bytes, bytearray)):
        # Preserve differences instead of silently dropping bytes.
        return bytes(val).decode("utf-8", errors="backslashreplace").strip()

    if isinstance(val, Decimal):
        try:
            val = float(val)
        except Exception:
            return str(val).strip()

    if isinstance(val, (int, float)):
        if isinstance(val, float):
            if math.isnan(val):
                return "NaN"
            if math.isinf(val):
                return "Inf" if val > 0 else "-Inf"
            val = round(val, float_round)
            if abs(val - round(val)) < 1e-12:
                return int(round(val))
        return val

    if isinstance(val, (datetime.datetime, datetime.date, datetime.time)):
        if isinstance(val, datetime.datetime):
            return val.replace(microsecond=0).isoformat(sep=" ")
        if isinstance(val, datetime.time):
            return val.replace(microsecond=0).isoformat()
        return val.isoformat()

    if isinstance(val, str):
        s = val.strip()
        if s in (r"\N", "\\N", "NULL", "null"):
            return None
        s = _normalize_datetime_string(s)
        if coerce_numeric_strings:
            num = _to_number_if_possible(s)
            if num is not None:
                if isinstance(num, float) and not (math.isnan(num) or math.isinf(num)):
                    num = round(num, float_round)
                    if abs(num - round(num)) < 1e-12:
                        return int(round(num))
                return num
        return s

    return str(val).strip()


def normalize_row(row, **kwargs):
    """Normalize a DB row (tuple/list) into a comparable tuple."""
    if row is None:
        return None
    return tuple(normalize_value(v, **kwargs) for v in row)


def rows_are_equal(row_a, row_b, *, float_tol: float = 1e-3) -> bool:
    """Row-level comparison with float tolerance."""
    if row_a is None or row_b is None:
        return row_a == row_b
    if len(row_a) != len(row_b):
        return False

    for a, b in zip(row_a, row_b):
        if a is None or b is None:
            if a != b:
                return False
            continue

        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            fa, fb = float(a), float(b)
            if math.isnan(fa) and math.isnan(fb):
                continue
            if abs(fa - fb) > float_tol:
                return False
            continue

        if str(a) != str(b):
            return False

    return True

def check_result_same(
    result_a,
    result_b,
    check_order: bool = False,
    *,
    float_tol: float = 1e-3,
    float_round: int = 3,
    coerce_numeric_strings: bool = True,
    unordered_fallback_on_order_mismatch: bool = True,
):
    """Compare two result sets with robust normalization.

    Design goal: reduce false mismatches across different DB drivers.

    - Normalizes values (numbers, decimals, datetime objects, common datetime strings, bytes).
    - Unordered comparison uses multiset (Counter) semantics.
    - If check_order=True, compares row-by-row first; optionally falls back to unordered
      comparison on mismatch (helps when ORDER BY is present but ties make order unstable).
    """
    if result_a is None or result_b is None:
        return False

    norm_a = [
        normalize_row(r, float_round=float_round, coerce_numeric_strings=coerce_numeric_strings)
        for r in result_a
    ]
    norm_b = [
        normalize_row(r, float_round=float_round, coerce_numeric_strings=coerce_numeric_strings)
        for r in result_b
    ]

    if len(norm_a) != len(norm_b):
        return False

    def unordered_equal() -> bool:
        # Tolerance-aware multiset (bag) comparison.
        # Greedy matching is slower than Counter but matches the legacy behavior
        # and greatly reduces false mismatches due to float noise / driver typing.
        pool = list(norm_b)
        for ra in norm_a:
            found = False
            for idx, rb in enumerate(pool):
                if rows_are_equal(ra, rb, float_tol=float_tol):
                    pool.pop(idx)
                    found = True
                    break
            if not found:
                return False
        return True

    if check_order:
        ordered_ok = True
        for ra, rb in zip(norm_a, norm_b):
            if not rows_are_equal(ra, rb, float_tol=float_tol):
                ordered_ok = False
                break
        if ordered_ok:
            return True
        return unordered_equal() if unordered_fallback_on_order_mismatch else False

    return unordered_equal()
             
def clean_llm_sql(text):
    """
    Extract SQL from LLM response (markdown blocks).
    """
    pattern = r"```(value:sql|tsql|mssql|mysql|postgresql|oracle)value\s*(.*value)\s*```"
    match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
    sql = match.group(1).strip() if match else text.strip()
    return sql

def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_json(data, path):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


