"""Oracle public-entry regressions; no database or model requests."""
from decimal import Decimal
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

try:
    from . import evaluate, oracle_ex
except ImportError:
    import evaluate
    import oracle_ex


class PublicOracleTests(unittest.TestCase):
    def evidence(self, gt, pred, *, reason='match', pair_timeout=False,
                 gt_timeout=False, pred_timeout=False):
        return {
            'comparison_policy': oracle_ex.comparison_policy(),
            'comparison': {'reason': reason},
            'pair_timeout': pair_timeout,
            'gt': {'timeout': gt_timeout}, 'pred': {'timeout': pred_timeout},
            'typed_results': {'gt': oracle_ex.encode_result(gt),
                              'pred': oracle_ex.encode_result(pred)},
        }

    def test_structured_errors_and_legacy_detection(self):
        error = {'__uniql_execution_error__': True, 'message': 'ORA-01791'}
        self.assertEqual(evaluate.collect_db_errors(error, error),
                         ['ground_truth: ORA-01791', 'predicted: ORA-01791'])
        self.assertEqual(evaluate.result_error_message(['mysql Error: missing']),
                         'mysql Error: missing')
        self.assertIsNone(evaluate.result_error_message([('valid result',)]))

    def test_oracle_dispatch_uses_budget_grading_and_exact_evidence(self):
        constructors = []
        rows = [(Decimal('9007199254740993.123456789'), b'\x00\xff')]
        info = self.evidence(rows, rows)

        class Evaluator:
            def __init__(self, *args, **kwargs):
                constructors.append((args, kwargs))
                self.last_evaluation = info

            def check_result_same(self):
                return True, rows, rows

        with patch.object(evaluate.importlib, 'import_module',
                          return_value=SimpleNamespace(OracleEvaluater=Evaluator)):
            with patch.object(evaluate, 'func_timeout', side_effect=AssertionError('outer thread')):
                result = evaluate.execute_model('SELECT 1', 'SELECT 1', 'db.sqlite',
                                                7, 240, 'oracle', 'list')
        self.assertEqual(constructors[0][1],
                         {'grading_method': 'list', 'query_timeout': 120, 'total_timeout': 240})
        self.assertTrue(result['res'])
        self.assertEqual(result['comparison_version'], 'oracle-ex-bag-finite-float-v1')
        # Compatibility JSON fields may round Decimal; the authoritative fields cannot.
        encoded = json.loads(json.dumps(evaluate.json_safe(result)))
        self.assertEqual(encoded['typed_results'], info['typed_results'])

    def test_legacy_execute_sql_still_returns_three_values(self):
        class Evaluator:
            def __init__(self, *args, **kwargs):
                pass

            def check_result_same(self):
                return True, [(1,)], [(1,)]

        with patch.object(evaluate.importlib, 'import_module',
                          return_value=SimpleNamespace(OracleEvaluater=Evaluator)):
            self.assertEqual(evaluate.execute_sql('SELECT 1', 'SELECT 1', 'db.sqlite', 'oracle'),
                             (True, [(1,)], [(1,)]))

    def test_oracle_result_text_is_not_mistaken_for_error(self):
        rows = [('legitimate Error: text',)]
        with patch.object(evaluate, 'execute_sql',
                          return_value=(True, rows, rows, self.evidence(rows, rows))):
            result = evaluate.execute_model('SELECT 1', 'SELECT 1', 'db.sqlite', 0, 120, 'oracle')
        self.assertTrue(result['res'])
        self.assertIsNone(result['error'])

    def test_identical_oracle_execution_errors_never_score(self):
        error = {'__uniql_execution_error__': True, 'message': 'ORA-01791', 'timeout': False}
        with patch.object(evaluate, 'execute_sql', return_value=(True, error, error,
                          self.evidence(None, None, reason='execution_failed'))):
            result = evaluate.execute_model('gold', 'pred', 'db.sqlite', 0, 120, 'oracle')
        self.assertEqual(result['res'], 0)
        self.assertIn('ground_truth: ORA-01791', result['error'])
        self.assertIn('predicted: ORA-01791', result['error'])
        self.assertFalse(result['timeout'])

    def test_pair_budget_and_native_timeout_propagate(self):
        rows = [(1,)]
        for reason, pair, gt, pred in (
                ('pair_budget_exhausted', True, False, False),
                ('execution_failed', False, True, False),
                ('execution_failed', False, False, True)):
            info = self.evidence(rows, rows, reason=reason, pair_timeout=pair,
                                 gt_timeout=gt, pred_timeout=pred)
            with self.subTest(reason=reason, gt=gt, pred=pred):
                with patch.object(evaluate, 'execute_sql', return_value=(False, rows, rows, info)):
                    result = evaluate.execute_model('gold', 'pred', 'db.sqlite', 0, 120, 'oracle')
                self.assertTrue(result['timeout'])
                self.assertFalse(result['res'])
                if pair:
                    self.assertEqual(result['error'], 'pair_budget_exhausted')

    def test_pair_timeout_does_not_overwrite_primary_error(self):
        error = {'__uniql_execution_error__': True, 'message': 'ORA-00942'}
        info = self.evidence(None, None, reason='execution_failed', pair_timeout=True)
        with patch.object(evaluate, 'execute_sql', return_value=(False, error, error, info)):
            result = evaluate.execute_model('gold', 'pred', 'db.sqlite', 0, 120, 'oracle')
        self.assertTrue(result['timeout'])
        self.assertIn('ORA-00942', result['error'])

    def test_comparison_and_encoding_errors_are_reported(self):
        for reason in ('comparison_error', 'typed_evidence_encoding_failed'):
            info = self.evidence(None, None, reason=reason)
            with self.subTest(reason=reason):
                with patch.object(evaluate, 'execute_sql', return_value=(False, None, None, info)):
                    result = evaluate.execute_model('gold', 'pred', 'db.sqlite', 0, 120, 'oracle')
                self.assertEqual(result['error'], reason)
                self.assertEqual(result['res'], 0)

    def test_other_dialects_keep_func_timeout_and_error_guard(self):
        with patch.object(evaluate, 'func_timeout', return_value=(True, [(1,)], [(1,)])) as timeout:
            with patch.object(evaluate, 'execute_sql', side_effect=AssertionError('unexpected call')):
                result = evaluate.execute_model('gold', 'pred', 'db.sqlite', 0, 120, 'sqlite')
        self.assertTrue(result['res'])
        timeout.assert_called_once()
        self.assertNotIn('comparison_policy', result)
        with patch.object(evaluate, 'func_timeout',
                          return_value=(True, ['mysql Error: failure'], ['mysql Error: failure'])):
            result = evaluate.execute_model('gold', 'pred', 'db.sqlite', 0, 120, 'mysql')
        self.assertEqual(result['res'], 0)

    def test_grading_metadata_is_read_from_prediction_file(self):
        with TemporaryDirectory() as work:
            path = Path(work) / 'predictions.json'
            path.write_text(json.dumps([
                {'pred_sqls': ['SELECT 1'], 'ground_truth_sql': 'SELECT 1',
                 'db_id': 'db', 'grading_method': 'list'},
                {'pred_sqls': [], 'ground_truth_sql': 'SELECT 1', 'db_id': 'db'},
            ]))
            predicted, _, _, metadata = evaluate.package_sqls(path, work)
        self.assertEqual(predicted, ['SELECT 1', ''])
        self.assertEqual([m['grading_method'] for m in metadata], ['list', None])

    def test_parallel_passes_metadata_without_running_workers(self):
        with patch.object(evaluate.mp, 'Pool') as factory:
            evaluate.run_sqls_parallel([('pred', 'gold')], ['db.sqlite'], dialect='oracle',
                                      metadata=[{'grading_method': 'list'}])
        kwargs = factory.return_value.apply_async.call_args.kwargs
        self.assertEqual(kwargs['args'][-1], 'list')
        with self.assertRaises(ValueError):
            evaluate.run_sqls_parallel([('pred', 'gold')], [], metadata=[])

    def test_runtime_requires_oracle_parser(self):
        with patch.object(evaluate.importlib.util, 'find_spec',
                          side_effect=lambda name: None if name == 'sqlglot' else object()):
            with self.assertRaisesRegex(RuntimeError, 'sqlglot'):
                evaluate.validate_runtime('oracle')


if __name__ == '__main__':
    unittest.main()
