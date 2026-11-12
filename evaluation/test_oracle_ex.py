"""File-only Oracle EX regressions; no database, model or migration execution.

Run directly or as evaluation.test_oracle_ex / UniQL.evaluation.test_oracle_ex.
Set ORACLE_EX_DIFFERENTIAL=1 in the existing Oracle preparation venv to opt into
read-only import of the frozen SQLGlot translation oracle (6,000 seeded cases).
Normal tests and the production module need only the standard library.
"""
import ast
import datetime as dt
from decimal import Decimal
import hashlib
import importlib.util
import inspect
import json
import math
import os
from pathlib import Path
import random
import subprocess
import sys
import unittest
from zoneinfo import ZoneInfo

if __package__:
    from . import oracle_ex as ex
else:
    import oracle_ex as ex


ROOT = Path(__file__).resolve().parents[1]
FROZEN = Path(os.getenv('ORACLE_EX_REFERENCE_PATH', str(ROOT / 'migration/oracle/translation.py')))
FROZEN_SHA256 = 'ab1143246e2fb29e7d88a7ed342ba03178cad48fd01c4327a60ec4e8154705ca'
FUNCTIONS = ('comparison_policy', '_key', '_preview', '_matches', 'verify_results_oracle')


def compare(source, target, **kwargs):
    return ex.verify_results_oracle(source, target, **dict(
        {'source_columns': 1, 'target_columns': 1}, **kwargs))


def decode_scalar(tag):
    """Test-only independent decoder proving lossless JSON scalar evidence."""
    kind, value = tag['type'], tag['value']
    if kind == 'NoneType':
        return None
    if kind in ('bool', 'str'):
        return value
    if kind == 'int':
        return int(value)
    if kind == 'float':
        return float.fromhex(value)
    if kind == 'Decimal':
        return Decimal(value)
    if kind == 'bytes':
        return bytes.fromhex(value)
    if kind == 'timedelta':
        return dt.timedelta(days=value[0], seconds=value[1], microseconds=value[2])
    if kind == 'date':
        return dt.date.fromisoformat(value)
    parsed = (dt.datetime if kind == 'datetime' else dt.time).fromisoformat(value)
    timezone = tag['tz']
    if timezone is None:
        tz = None
    elif timezone['type'] == 'ZoneInfo':
        tz = ZoneInfo(timezone['key'])
    else:
        days, seconds, micros = timezone['offset']
        tz = dt.timezone(dt.timedelta(days=days, seconds=seconds, microseconds=micros),
                         timezone['name'])
    return parsed.replace(tzinfo=tz, fold=tag['fold'])


class ComparatorTests(unittest.TestCase):
    def test_fixed_numeric_policy(self):
        self.assertEqual(ex.VERSION, 'oracle-ex-bag-finite-float-v1')
        self.assertFalse(ex.comparison_policy()['official'])
        self.assertEqual(ex.ABS_TOL, 1e-8)
        self.assertEqual(ex.REL_TOL, 1e-9)

    def test_duplicates_and_row_counts(self):
        self.assertTrue(compare([(1,), (1,), (2,)], [(2,), (1,), (1,)])['passed'])
        record = compare([(1,), (1,), (2,)], [(2,), (2,), (1,)])
        self.assertFalse(record['passed'])
        self.assertEqual(record['unmatched_count'], 1)
        self.assertEqual(compare([(1,)], [(1,), (1,)])['reason'], 'row_count_mismatch')

    def test_empty_requires_real_cursor_widths(self):
        self.assertTrue(compare([], [])['passed'])
        for width in (None, 0, -1, True, '1', 1.0):
            self.assertEqual(compare([], [], source_columns=width)['reason'],
                             'missing_cursor_column_count')
        self.assertEqual(compare([], [], target_columns=2)['reason'], 'column_count_mismatch')
        self.assertEqual(compare([], [(1,)])['reason'], 'row_count_mismatch')

    def test_malformed_rows_and_column_positions(self):
        for source in ([()], [(1, 2)], [1], [{'v': 1}]):
            self.assertEqual(compare(source, [(1,)])['reason'], 'comparison_error')
        self.assertFalse(compare([(1, 'x')], [('x', 1)], source_columns=2,
                                 target_columns=2)['passed'])
        self.assertTrue(compare([(1, 'x')], [(1, 'x')], source_columns=2,
                                target_columns=2)['passed'])

    def test_huge_integers_and_two_to_53(self):
        for value in (2**53 + 1, 2**63 - 1, 10**100 + 1, -(10**100 + 1)):
            self.assertTrue(compare([(value,)], [(Decimal(value),)])['passed'])
            self.assertFalse(compare([(value,)], [(float(value),)])['passed'])
            self.assertFalse(compare([(value,)], [(value + 1,)])['passed'])
        self.assertTrue(compare([(2**53,)], [(float(2**53),)])['passed'])
        self.assertFalse(compare([(1,)], [(1.0 + 1e-10,)])['passed'])

    def test_decimal_precision_is_exact_without_float(self):
        a = Decimal('12345678901234567890.123456789012345678901')
        b = Decimal('12345678901234567890.123456789012345678902')
        self.assertFalse(compare([(a,)], [(b,)])['passed'])
        self.assertFalse(compare([(Decimal('0.1'),)], [(Decimal('0.1000000001'),)])['passed'])
        self.assertTrue(compare([(Decimal('1.00'),)], [(1,)])['passed'])
        self.assertTrue(compare([(Decimal('0.1'),)], [(0.1,)])['passed'])

    def test_float_absolute_and_relative_tolerance(self):
        for method in ('list', 'set'):
            self.assertTrue(compare([(0.0,)], [(Decimal('1e-8'),)], grading_method=method)['passed'])
            self.assertTrue(compare([(0.0,)], [(math.nextafter(1e-8, 0.0),)],
                                    grading_method=method)['passed'])
            # The binary float 1e-8 is slightly above the exact decimal threshold.
            self.assertFalse(compare([(0.0,)], [(1e-8,)], grading_method=method)['passed'])
            self.assertFalse(compare([(0.0,)], [(math.nextafter(1e-8, math.inf),)],
                                     grading_method=method)['passed'])
            record = compare([(1e9,)], [(1e9 + 0.5,)], grading_method=method)
            self.assertTrue(record['passed'])
            self.assertEqual(record['numeric_diagnostics']['tolerated_rows'], 1)
            self.assertEqual(record['numeric_diagnostics']['max_delta'], '1/2')
            self.assertFalse(compare([(1e9,)], [(1e9 + 2.0,)], grading_method=method)['passed'])
        self.assertTrue(compare([(1e308,)], [(math.nextafter(1e308, 0.0),)])['passed'])

    def test_exact_first_one_to_one_matching(self):
        record = compare([(0.0,), (9e-9,)], [(9e-9,), (-9e-9,)])
        self.assertTrue(record['passed'])
        self.assertEqual(record['original_mismatch_count'], 1)
        self.assertEqual(record['numeric_diagnostics']['tolerated_rows'], 1)
        self.assertFalse(compare([(0.0,), (0.0,)], [(1e-8,), (1.0,)])['passed'])
        # Preserve the original residual greedy false negative, not max matching.
        self.assertFalse(compare([(0.0,), (-1e-8,)], [(-5e-9,), (5e-9,)])['passed'])

    def test_ordered_has_no_bag_fallback_and_subset_is_metadata(self):
        source, target = [(1,), (2,)], [(2,), (1,)]
        record = compare(source, target, grading_method='list')
        self.assertFalse(record['passed'])
        self.assertEqual(record['mode'], 'ordered')
        self.assertEqual(record['differences'][0]['target'], [{'type': 'int', 'value': '2'}])
        for method in (None, 'set', 'subset,=,1', 'LIST'):
            self.assertTrue(compare(source, target, grading_method=method)['passed'])
        self.assertFalse(compare([(1,)], target, grading_method='subset,>=,1')['passed'])

    def test_text_bytes_null_bool_are_typed_exact(self):
        for a, b in [(' x ', 'x'), ('01', '1'), ('1', 1), ('1', b'1'),
                     (b'\x00', '\x00'), ('NULL', None), ('', None), (True, 1),
                     (False, 0), ('A', 'a'), (r'\N', None)]:
            with self.subTest(a=a, b=b):
                self.assertFalse(compare([(a,)], [(b,)])['passed'])
        for value in (None, True, False, ' x \x00 😀 ', b'\x00\xff'):
            self.assertTrue(compare([(value,)], [(value,)])['passed'])

    def test_temporal_typed_exact_and_fold(self):
        a = dt.datetime(2026, 11, 1, 1, 30, fold=0)
        self.assertFalse(compare([(a,)], [(a.replace(fold=1),)])['passed'])
        self.assertFalse(compare([(dt.date(2026, 1, 1),)],
                                 [(dt.datetime(2026, 1, 1),)])['passed'])
        utc = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
        offset = utc.astimezone(dt.timezone(dt.timedelta(hours=1)))
        self.assertFalse(compare([(utc,)], [(offset,)])['passed'])

    def test_execution_failure_not_empty_success(self):
        for kwargs in ({'source': None, 'target': []}, {'source': [], 'target': None},
                       {'source': [], 'target': [], 'source_error': 'timeout'},
                       {'source': [], 'target': [], 'target_error': 'native error'}):
            record = compare(**kwargs)
            self.assertFalse(record['passed'])
            self.assertEqual(record['reason'], 'execution_failed')
        self.assertIsNone(compare(None, [])['source']['row_count'])

    def test_nonfinite_and_unsupported_fail_closed(self):
        for value in (float('nan'), float('inf'), -float('inf'), Decimal('NaN'),
                      Decimal('sNaN'), Decimal('Infinity'), object(), bytearray(b'x')):
            for method in ('list', 'set'):
                record = compare([(value,)], [(value,)], grading_method=method)
                self.assertFalse(record['passed'])
                self.assertEqual(record['reason'], 'comparison_error')
                self.assertIsNotNone(record['comparison_error'])

    def test_bounded_differences_not_bounded_comparison(self):
        record = compare([(i,) for i in range(8)], [(100 + i,) for i in range(8)])
        self.assertEqual(record['unmatched_count'], 8)
        self.assertEqual(len(record['differences']), 5)
        self.assertEqual(ex._preview(['x' * 200, b'a' * 100]),
                         [{'type': 'str', 'value': 'x' * 160},
                          {'type': 'bytes', 'value': (b'a' * 80).hex()}])

    def test_production_import_has_no_nonstdlib_dependencies(self):
        tree = ast.parse(Path(ex.__file__).read_text(encoding='utf-8'))
        allowed = {'bisect', 'collections', 'datetime', 'decimal', 'fractions', 'math', 'zoneinfo'}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                self.assertTrue(all(alias.name in allowed for alias in node.names))
            elif isinstance(node, ast.ImportFrom):
                self.assertIn(node.module, allowed)
                self.assertEqual(node.level, 0)
        script = """
import builtins, runpy, sys
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name.split('.')[0] in {'migration', 'sqlglot', 'oracledb', 'evaluation', 'construction'}:
        raise AssertionError('Forbidden dependency import: ' + name)
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
module = runpy.run_path(sys.argv[1])
assert module['verify_results_oracle']([], [], source_columns=1, target_columns=1)['passed']
assert module['encode_result']([(1,)]) == [[{'type': 'int', 'value': '1'}]]
assert not any('migration' in name or 'sqlglot' in name for name in sys.modules)
"""
        result = subprocess.run([sys.executable, '-I', '-B', '-c', script, ex.__file__],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)


class EncodingTests(unittest.TestCase):
    def test_none_and_empty_remain_distinct(self):
        self.assertIsNone(ex.encode_result(None))
        self.assertEqual(ex.encode_result([]), [])
        self.assertEqual(ex.encode_result(()), [])

    def test_exact_typed_json_roundtrip(self):
        offset = dt.timezone(dt.timedelta(hours=5, seconds=1, microseconds=2), 'custom')
        zone = ZoneInfo('UTC')
        values = [None, True, False, 2**53 + 1, 10**120, -0.0, 0.0,
                  math.nextafter(0.0, 1.0), 1e308,
                  Decimal('12345678901234567890.12345678901234567890100'),
                  Decimal('-0.000'), ' 01 \x00 😀 ', b'\x00\xff' * 100,
                  dt.date(2026, 11, 1), dt.timedelta(days=-3, microseconds=7),
                  dt.datetime(2026, 11, 1, 1, 30, 0, 123456, fold=1),
                  dt.datetime(2026, 11, 1, 1, 30, tzinfo=offset, fold=1),
                  dt.datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=1),
                  dt.time(1, 30, 0, 123456, tzinfo=offset, fold=1)]
        rows = [tuple(values), list(values)]
        encoded = ex.encode_result(rows)
        loaded = json.loads(json.dumps(encoded, ensure_ascii=True, allow_nan=False))
        self.assertEqual(len(loaded), 2)
        self.assertEqual(loaded[0], loaded[1])
        self.assertEqual(len(loaded[0]), len(values))
        for original, tag in zip(values, loaded[0]):
            decoded = decode_scalar(tag)
            self.assertIs(type(decoded), type(original))
            self.assertEqual(ex._key(decoded), ex._key(original))
            if type(original) is float:
                self.assertEqual(decoded.hex(), original.hex())
            if type(original) is Decimal:
                self.assertEqual(decoded.as_tuple(), original.as_tuple())
            if type(original) in (dt.datetime, dt.time):
                self.assertEqual(decoded.fold, original.fold)
                self.assertIs(type(decoded.tzinfo), type(original.tzinfo))
                if type(original.tzinfo) is ZoneInfo:
                    self.assertEqual(decoded.tzinfo.key, original.tzinfo.key)
                elif original.tzinfo is not None:
                    self.assertEqual(decoded.tzname(), original.tzname())
        self.assertEqual(encoded[0][3], {'type': 'int', 'value': str(2**53 + 1)})
        self.assertEqual(encoded[0][5], {'type': 'float', 'value': '-0x0.0p+0'})
        self.assertEqual(encoded[0][11]['value'], values[11])
        self.assertEqual(encoded[0][12]['value'], values[12].hex())

    def test_encoding_is_separate_from_matching(self):
        self.assertTrue(compare([(1,)], [(Decimal('1.00'),)])['passed'])
        self.assertNotEqual(ex.encode_result([(1,)]), ex.encode_result([(Decimal('1.00'),)]))
        self.assertNotEqual(ex.encode_result([(-0.0,)]), ex.encode_result([(0.0,)]))
        self.assertTrue(compare([(-0.0,)], [(0.0,)])['passed'])
        rows = [(1, 'a'), (1, 'a')]
        self.assertEqual(len(ex.encode_result(rows)), 2)
        self.assertNotEqual(ex.encode_result([(1, 'a')]), ex.encode_result([('a', 1)]))

    def test_encoding_rejects_lossy_unknown_nonfinite_and_ragged_values(self):
        for value in (float('nan'), float('inf'), Decimal('NaN'), Decimal('sNaN'),
                      Decimal('-Infinity'), object(), bytearray(b'x')):
            with self.assertRaises((TypeError, ValueError)):
                ex.encode_result([(value,)])
        for rows in ([1], [{'a': 1}], [(1,), (1, 2)], 'rows', iter([(1,)])):
            with self.assertRaises((TypeError, ValueError)):
                ex.encode_result(rows)
        class CustomTimezone(dt.tzinfo):
            def utcoffset(self, value):
                return dt.timedelta(0)
        with self.assertRaises(TypeError):
            ex.encode_result([(dt.datetime(2026, 1, 1, tzinfo=CustomTimezone()),)])


@unittest.skipUnless(os.environ.get('ORACLE_EX_DIFFERENTIAL') == '1',
                     'Opt-in frozen comparator import requires the existing preparation venv')
class FrozenDifferentialTests(unittest.TestCase):
    def test_6000_seeded_complete_records(self):
        before = FROZEN.read_bytes()
        self.assertEqual(hashlib.sha256(before).hexdigest(), FROZEN_SHA256)
        spec = importlib.util.spec_from_file_location('frozen_oracle_ex_differential', FROZEN)
        frozen = importlib.util.module_from_spec(spec)
        # Avoid creating bytecode beside any frozen migration source.
        previous = sys.dont_write_bytecode
        sys.dont_write_bytecode = True
        try:
            spec.loader.exec_module(frozen)
        finally:
            sys.dont_write_bytecode = previous
        self.assertEqual(ex.comparison_policy(), frozen.comparison_policy())
        rng = random.Random(20261111)
        pool = [None, True, False, -1, 0, 1, 2**53, 2**53 + 1, 10**100 + 1,
                -0.0, 0.0, 1e-8, -1e-8, 5e-9, -5e-9, 0.1, 1.0, 1e9, 1e308,
                Decimal('0.1'), Decimal('0.1000000001'), Decimal('1.00'),
                Decimal('12345678901234567890.123456789012345678901'),
                '', ' ', '01', '1', 'NULL', '😀\x00', 'x' * 200, b'', b'1', b'\xff' * 100,
                dt.date(2026, 11, 1), dt.datetime(2026, 11, 1, fold=1),
                dt.time(1, 30, fold=1), dt.timedelta(days=-1, microseconds=1)]
        for case in range(6000):
            width = rng.randint(1, 4)
            source = [tuple(rng.choice(pool) for _ in range(width))
                      for _ in range(rng.randint(0, 9))]
            target = list(source)
            action = case % 12
            if action == 0:
                target = [tuple(rng.choice(pool) for _ in range(width)) for _ in source]
            elif action == 1 and source:
                target.append(source[0])
            elif action == 2 and source:
                source.append(source[0])
            elif action == 3 and source:
                target[0] = tuple(reversed(target[0]))
            elif action == 4:
                source = [(rng.choice([0.0, 1.0, 1e9, 1e308]),) for _ in range(5)]
                width = 1
                target = [(math.nextafter(v, math.inf),) for (v,) in source]
            elif action == 5:
                source, target, width = [(0.0,), (-1e-8,)], [(-5e-9,), (5e-9,)], 1
            elif action == 6:
                source, target, width = [(0.0,), (1e-8,)], [(1e-8,), (-1e-8,)], 1
            elif action == 7:
                value = rng.choice([float('nan'), float('inf'), Decimal('NaN'),
                                    Decimal('sNaN'), Decimal('Infinity'), bytearray(b'x')])
                source, target, width = [(value,)], [(value,)], 1
            elif action == 8 and source:
                target[0] = target[0] + (1,)
            elif action == 9 and source:
                target[0] = list(target[0])
            rng.shuffle(target)
            kwargs = {'source_columns': width, 'target_columns': width,
                      'grading_method': rng.choice([None, 'set', 'list', 'subset,=,3'])}
            if action == 10:
                kwargs['source_columns'] = rng.choice([None, 0, -1, True, '1'])
            if action == 11:
                mutation = rng.randrange(4)
                if mutation == 0:
                    source = None
                elif mutation == 1:
                    target = None
                elif mutation == 2:
                    kwargs['target_error'] = 'native failure'
                else:
                    kwargs['target_columns'] = width + 1
            # Whole dict equality includes passed, differences, policy, errors,
            # cursor metadata, reason, counts, mode and numeric diagnostics.
            self.assertEqual(ex.verify_results_oracle(source, target, **kwargs),
                             frozen.verify_results_oracle(source, target, **kwargs),
                             'seed=20261111 case=' + str(case))
        self.assertEqual(FROZEN.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
