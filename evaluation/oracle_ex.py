"""Fixed project instance EX copied from migration/oracle/translation.py.

The comparator functions and numeric constants are exact copies of the frozen
oracle-ex-bag-finite-float-v1 policy, not the official Platinum grader and not a
universal SQL equivalence test. This stdlib-only module deliberately imports no
migration, loader, SQLGlot or shared EX verifier code. Tolerance, typed exactness,
exact-first residual greedy bag matching and strictly ordered lists stay fixed.

encode_result is separate lossless JSON evidence, not comparison normalization.
Cursor column counts must still be supplied to verify_results_oracle, including
for empty results; scalar tags and column positions do not replace metadata.
"""
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
import datetime as dt
from decimal import Decimal
from fractions import Fraction
import math

VERSION = 'oracle-ex-bag-finite-float-v1'
ABS_TOL = 1e-8
REL_TOL = 1e-9
_ABS = Fraction(str(ABS_TOL))
_REL = Fraction(str(REL_TOL))


def comparison_policy():
    return {'version': VERSION, 'official': False, 'abs_tol': ABS_TOL, 'rel_tol': REL_TOL,
            'tolerance': 'finite float/float or float/Decimal only; abs(a-b) <= max(abs_tol, rel_tol*max(abs(a),abs(b)))',
            'integer': 'exact mathematical value, including against float/Decimal',
            'rows': 'exact-first then source-order residual greedy one-to-one bag; list strictly ordered',
            'false_negatives': 'possible from non-transitive residual greedy matching; no unordered fallback',
            'text_binary_null_bool_temporal': 'typed exact, no coercion',
            'other_grading_methods': 'metadata only; not official set/subset',
            'migration': 'not applicable; migration fingerprints remain exact'}


def _key(value):
    kind = type(value)
    if value is None:
        return ('null',)
    if kind is bool:
        return ('bool', value)
    if kind in (int, float, Decimal):
        if kind is float and not math.isfinite(value) or kind is Decimal and not value.is_finite():
            raise ValueError('Nonfinite numeric value')
        return ('number', Fraction(value))
    if kind is str:
        return ('text', value)
    if kind is bytes:
        return ('bytes', value)
    if kind in (dt.datetime, dt.time):
        return (kind.__name__, value.isoformat(), value.fold)
    if kind is dt.date:
        return ('date', value.isoformat())
    if kind is dt.timedelta:
        return ('timedelta', value.days, value.seconds, value.microseconds)
    raise TypeError('Unsupported value type: ' + kind.__name__)


def _preview(row):
    result = []
    for value in row:
        kind = type(value)
        if kind in (int, float, Decimal):
            payload = str(value)
        elif kind is bytes:
            payload = value[:80].hex()
        elif kind is str:
            payload = value[:160]
        elif value is None or kind is bool:
            payload = value
        else:
            payload = _key(value)[1:]
        result.append({'type': kind.__name__, 'value': payload})
    return result


def _matches(left, right):
    for a, b in zip(left, right):
        ka, kb = _key(a), _key(b)
        if ka == kb:
            continue
        if ka[0] != 'number' or kb[0] != 'number' or type(a) is int or type(b) is int:
            return False
        if type(a) is not float and type(b) is not float:
            return False
        x, y = ka[1], kb[1]
        if abs(x - y) > max(_ABS, _REL * max(abs(x), abs(y))):
            return False
    return True


def verify_results_oracle(source, target, source_error=None, target_error=None,
                      source_columns=None, target_columns=None, grading_method=None):
    """Full result EX with mandatory cursor widths and typed bounded differences."""
    record = {'version': VERSION, 'policy': comparison_policy(),
              'mode': 'ordered' if grading_method == 'list' else 'bag',
              'grading_method': grading_method, 'passed': False, 'comparison_error': None,
              'original_mismatch_count': None, 'unmatched_count': None,
              'numeric_diagnostics': {'tolerated_rows': 0, 'max_delta': '0'}, 'differences': []}
    for side, rows, error, width in (('source', source, source_error, source_columns),
                                     ('target', target, target_error, target_columns)):
        record[side] = {'success': rows is not None and not error, 'error': error,
                        'row_count': len(rows) if rows is not None else None, 'column_count': width}
    if not record['source']['success'] or not record['target']['success']:
        record['reason'] = 'execution_failed'
        return record
    if any(type(w) is not int or w <= 0 for w in (source_columns, target_columns)):
        record['reason'] = 'missing_cursor_column_count'
        return record
    if source_columns != target_columns:
        record['reason'] = 'column_count_mismatch'
        return record
    try:
        def keys(rows):
            result = []
            for row in rows:
                if type(row) not in (tuple, list) or len(row) != source_columns:
                    raise ValueError('Row width disagrees with cursor metadata')
                result.append(tuple(_key(v) for v in row))
            return result
        left, right = keys(source), keys(target)
        if len(left) != len(right):
            record['reason'] = 'row_count_mismatch'
            return record
        max_delta = Fraction(0)

        def note(a, b):
            nonlocal max_delta
            record['numeric_diagnostics']['tolerated_rows'] += 1
            for x, y in zip(a, b):
                if type(x) in (int, float, Decimal) and type(y) in (int, float, Decimal):
                    max_delta = max(max_delta, abs(Fraction(x) - Fraction(y)))

        if record['mode'] == 'ordered':
            mismatch = [(i, i) for i, (a, b) in enumerate(zip(left, right)) if a != b]
            record['original_mismatch_count'] = len(mismatch)
            failed = []
            for i, j in mismatch:
                if _matches(source[i], target[j]):
                    note(source[i], target[j])
                else:
                    failed.append(i)
            for i in failed[:5]:
                record['differences'].append({'source': _preview(source[i]), 'target': _preview(target[i])})
        else:
            remaining = Counter(right)
            unmatched_left = []
            for i, key in enumerate(left):
                if remaining[key]:
                    remaining[key] -= 1
                else:
                    unmatched_left.append(i)
            record['original_mismatch_count'] = len(unmatched_left)
            buckets = defaultdict(list)
            for j, key in enumerate(right):
                if remaining[key]:
                    remaining[key] -= 1
                    signature = tuple(('number',) if k[0] == 'number' else k for k in key)
                    pivot = next((i for i, k in enumerate(key) if k[0] == 'number'), None)
                    value = key[pivot][1] if pivot is not None else Fraction(0)
                    buckets[signature].append((value, j))
            for bucket in buckets.values():
                bucket.sort()
            used, failed = set(), []
            for i in unmatched_left:
                key = left[i]
                signature = tuple(('number',) if k[0] == 'number' else k for k in key)
                bucket = buckets.get(signature, [])
                pivot = next((p for p, k in enumerate(key) if k[0] == 'number'), None)
                value = key[pivot][1] if pivot is not None else Fraction(0)
                radius = max(_ABS, _REL * abs(value) / (1 - _REL))
                lo = bisect_left(bucket, (value - radius, -1))
                hi = bisect_right(bucket, (value + radius, len(target)))
                found = None
                for _, j in bucket[lo:hi]:
                    if j not in used and _matches(source[i], target[j]):
                        found = j
                        break
                if found is None:
                    failed.append(i)
                else:
                    used.add(found)
                    note(source[i], target[found])
            for i in failed[:5]:
                record['differences'].append({'source': _preview(source[i])})
        record['unmatched_count'] = len(failed)
        record['numeric_diagnostics']['max_delta'] = str(max_delta)
        record['passed'] = not failed
        record['reason'] = 'match' if record['passed'] else 'result_mismatch'
    except (TypeError, ValueError, ArithmeticError) as exc:
        record['comparison_error'] = type(exc).__name__ + ': ' + str(exc)
        record['reason'] = 'comparison_error'
    return record


def _encode_timezone(value):
    """Preserve naive, fixed-offset and stdlib ZoneInfo timezone identities."""
    from zoneinfo import ZoneInfo

    timezone = value.tzinfo
    if timezone is None:
        return None
    if type(timezone) is dt.timezone:
        offset = timezone.utcoffset(None)
        return {'type': 'timezone', 'name': timezone.tzname(None),
                'offset': [offset.days, offset.seconds, offset.microseconds]}
    if type(timezone) is ZoneInfo and timezone.key is not None:
        return {'type': 'ZoneInfo', 'key': timezone.key}
    raise TypeError('Unsupported timezone type: ' + type(timezone).__name__)


def _encode_scalar(value):
    # Validate supported types and finite numerics without changing the value.
    _key(value)
    kind = type(value)
    result = {'type': kind.__name__}
    if value is None or kind in (bool, str):
        result['value'] = value
    elif kind in (int, Decimal):
        result['value'] = str(value)
    elif kind is float:
        result['value'] = value.hex()
    elif kind is bytes:
        result['value'] = value.hex()
    elif kind in (dt.datetime, dt.time):
        result.update(value=value.isoformat(), fold=value.fold, tz=_encode_timezone(value))
    elif kind is dt.date:
        result['value'] = value.isoformat()
    elif kind is dt.timedelta:
        result['value'] = [value.days, value.seconds, value.microseconds]
    return result


def encode_result(rows):
    """Return JSON-compatible rows of exact typed scalars, or None on no result.

    Keep every column position, row, duplicate, whitespace and byte; integers and
    Decimals are strings (no JSON precision loss), floats are hex (including signed
    zero), and temporal values retain ISO, fold and timezone identity. Unsupported
    scalars/timezones, nonfinite numbers and malformed/ragged rows raise rather
    than silently stringify. Empty rows encode as [], never substitute for None.
    """
    if rows is None:
        return None
    if type(rows) not in (list, tuple):
        raise TypeError('Expected a list or tuple of result rows')
    result = []
    width = None
    for row in rows:
        if type(row) not in (list, tuple):
            raise TypeError('Expected a list or tuple result row')
        if width is None:
            width = len(row)
        if len(row) != width:
            raise ValueError('Inconsistent result row width')
        result.append([_encode_scalar(value) for value in row])
    return result
