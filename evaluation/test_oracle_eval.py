"""Public Oracle adapter tests; no Oracle driver installation or live database."""
import datetime
from decimal import Decimal
import importlib
import json
import os
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

try:
    from . import oracle_eval as module
except ImportError:
    import oracle_eval as module

SQL = "select value from records"
REAL_TIMER = threading.Timer


class FakeLOB:
    def __init__(self, value, error=None):
        self.value, self.error = value, error

    def read(self):
        if self.error:
            raise self.error
        return self.value


class FakeTimer:
    latest = None

    def __init__(self, interval, callback):
        self.interval, self.callback = interval, callback
        self.daemon = False
        self.started = self.cancelled = self.joined = False
        FakeTimer.latest = self

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True

    def join(self, timeout=None):
        self.joined = True

    def is_alive(self):
        return False


class DriverError(Exception):
    def __init__(self, code, message="native error", full_code=None):
        detail = SimpleNamespace(code=code, full_code=full_code or "ORA-%05d" % code,
                                 message=message)
        super().__init__(detail)
        self.message = message

    def __str__(self):
        return self.message


class FakeCursor:
    def __init__(self, rows=(), width=1, *, description=True, execute_error=None,
                 fetch_error=None, close_error=None, on_query=None):
        self.rows = list(rows)
        self.arraysize = 1
        self.description = [("C%d" % i, "NUMBER") for i in range(width)] if description else None
        self.executed = []
        self.execute_error, self.fetch_error = execute_error, fetch_error
        self.close_error, self.on_query = close_error, on_query
        self.closed = False
        self.var = Mock()

    def execute(self, sql):
        self.executed.append(sql)
        if not sql.startswith(("ALTER SESSION", "SET TRANSACTION")):
            if self.on_query:
                self.on_query()
            if self.execute_error:
                raise self.execute_error

    def fetchmany(self, size):
        if self.fetch_error:
            raise self.fetch_error
        result, self.rows = self.rows[:size], self.rows[size:]
        return result

    def close(self):
        self.closed = True
        if self.close_error:
            raise self.close_error


class FakeConnection:
    def __init__(self, cursor=None, close_error=None, cursor_error=None, cancel_error=None):
        self.cur = cursor if cursor is not None else FakeCursor()
        self.close_error, self.cursor_error, self.cancel_error = close_error, cursor_error, cancel_error
        self.closed, self.cancel_count = False, 0

    def cursor(self):
        if self.cursor_error:
            raise self.cursor_error
        return self.cur

    def cancel(self):
        self.cancel_count += 1
        if self.cancel_error:
            raise self.cancel_error

    def close(self):
        self.closed = True
        if self.close_error:
            raise self.close_error


def driver_for(*connections):
    return SimpleNamespace(connect=Mock(side_effect=list(connections)), LOB=FakeLOB,
                           DB_TYPE_NUMBER="NUMBER", DB_TYPE_VARCHAR="VARCHAR")


class OracleEvaluatorTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.timer = patch.object(module.threading, "Timer", FakeTimer)
        self.timer.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(self.timer.stop)

    def evaluator(self, gold=SQL, pred=SQL, **kwargs):
        return module.OracleEvaluator("/data/sample.sqlite", gold, pred, **kwargs)

    def execute(self, cursor=None, connection=None, sql=SQL):
        connection = connection if connection is not None else FakeConnection(cursor)
        driver = driver_for(connection)
        with patch.dict(sys.modules, {"oracledb": driver}):
            result = self.evaluator()._execute_query(sql)
        return result, connection, driver

    def compare(self, left, right, *, gold=SQL, pred=SQL, grading_method=None, widths=(1, 1)):
        e = self.evaluator(gold, pred, grading_method=grading_method)
        driver = driver_for(FakeConnection(FakeCursor(left, widths[0])),
                            FakeConnection(FakeCursor(right, widths[1])))
        with patch.dict(sys.modules, {"oracledb": driver}):
            result = e.check_result_same()
        json.dumps(e.last_evaluation, allow_nan=False)
        return result, e

    def test_alias_and_lazy_driver_import(self):
        self.assertIs(module.OracleEvaluator, module.OracleEvaluater)
        with patch.dict(sys.modules, {"oracledb": None}):
            importlib.reload(module)
            self.evaluator()

    def test_missing_driver_is_execution_failure_not_admission(self):
        with patch.dict(sys.modules, {"oracledb": None}):
            rows, error, meta = self.evaluator()._execute_query(SQL)
        self.assertIsNone(rows)
        self.assertEqual(error["kind"], "driver_error")
        self.assertEqual(meta["error_stage"], "driver_import")
        self.assertFalse(meta["timeout"])

    def test_original_literals_identifiers_unicode_comments(self):
        sql = ' -- SELECT ignored\nWITH x AS (SELECT \'a;B\n中\' AS "MiXeD" FROM dual)\nSELECT "MiXeD" FROM x -- Keep\n; /* tail */\n'
        e = self.evaluator(sql, sql)
        self.assertEqual(e.oracle_gt, sql)
        self.assertEqual(e.oracle_pred, sql)
        cleaned = sql.replace('; /* tail */', ' /* tail */')
        self.assertEqual(e.clean_sql(sql), cleaned)
        (rows, error, _), con, _ = self.execute(FakeCursor([("a;B\n中",)]), sql=sql)
        self.assertIsNone(error)
        self.assertEqual(con.cur.executed[-1], cleaned)
        self.assertEqual(rows, [("a;B\n中",)])

    def test_clean_sql_removes_only_terminating_token(self):
        e = self.evaluator()
        for sql, expected in [("select ';' from dual; -- tail\n", "select ';' from dual -- tail\n"),
                              ("select 1 from dual -- tail\n;", "select 1 from dual -- tail\n"),
                              ("select 1 from dual /* ; */", "select 1 from dual /* ; */")]:
            with self.subTest(sql=sql):
                self.assertEqual(e.clean_sql(sql), expected)

    def test_admission_failures_never_connect(self):
        cases = ["", "-- SELECT only", "select 1 from dual;;", "select 1 from dual;select 2 from dual",
                 "drop table x", "delete from x", "begin null; end;", "explain plan for select 1 from dual",
                 "select 1 into x from dual", "select 1 from dual for update",
                 "select /*+ FULL(x) */ 1 from dual", "garbage SELECT 1 FROM dual"]
        driver = driver_for()
        with patch.dict(sys.modules, {"oracledb": driver}):
            for sql in cases:
                with self.subTest(sql=sql):
                    rows, error, meta = self.evaluator()._execute_query(sql)
                    self.assertIsNone(rows)
                    self.assertTrue(error["__uniql_execution_error__"])
                    self.assertEqual(meta["kind"], "admission_error")
                    self.assertFalse(meta["timeout"])
                    self.assertIsNone(meta["code"])
        driver.connect.assert_not_called()

    def test_query_timeout_validation(self):
        for timeout in (0, -1, 121, float("nan"), float("inf"), True, "120"):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                self.evaluator(query_timeout=timeout)

    def test_username_password_dsn_policy(self):
        e = self.evaluator()
        self.assertEqual(e.oracle_user, "SAMPLE")
        self.assertEqual(e.oracle_dsn, "localhost:1521/FREEPDB1")
        with self.assertRaises(ValueError):
            module.OracleEvaluator("bad-name.sqlite", SQL, SQL)
        with patch.dict(os.environ, {"UNIQL_ORACLE_USER": "Mixed User", "UNIQL_ORACLE_USER_PASSWORD": "reader",
                                     "UNIQL_ORACLE_PASSWORD": "admin", "UNIQL_ORACLE_DSN": "dsn"}):
            e = module.OracleEvaluator("bad-name.sqlite", SQL, SQL)
            self.assertEqual(e.oracle_user, "Mixed User")
            self.assertEqual(e.admin_pass, "reader")
            self.assertEqual(e.oracle_dsn, "dsn")
        with patch.dict(os.environ, {"UNIQL_ORACLE_PASSWORD": "fallback"}):
            self.assertEqual(self.evaluator().admin_pass, "fallback")

    def test_session_full_fetch_and_connection_options(self):
        rows = [(Decimal("9007199254740993"),)] * 2005
        (actual, error, meta), con, driver = self.execute(FakeCursor(rows))
        self.assertEqual(actual, rows)
        self.assertIsNone(error)
        self.assertEqual(con.cur.executed, list(module.SESSION_SQL) + ["SET TRANSACTION READ ONLY", SQL])
        self.assertTrue(meta["read_only_confirmed"])
        self.assertTrue(meta["cursor_closed"] and meta["connection_closed"])
        self.assertFalse(con.autocommit)
        self.assertLessEqual(con.call_timeout, 120000)
        self.assertEqual(driver.connect.call_args.kwargs["tcp_connect_timeout"], 15)
        self.assertEqual(driver.connect.call_args.kwargs["retry_count"], 0)
        self.assertTrue(FakeTimer.latest.cancelled and FakeTimer.latest.joined)

    def test_number_output_handler_modern_metadata(self):
        driver = driver_for()
        cursor = FakeCursor()
        handler = module.OracleEvaluator.number_output_handler(driver)
        handler(cursor, SimpleNamespace(type_code="NUMBER"))
        cursor.var.assert_called_once_with("VARCHAR", size=172, arraysize=1, outconverter=Decimal)
        self.assertIsNone(handler(cursor, SimpleNamespace(type_code="CLOB")))
        self.assertIsNone(handler(cursor, SimpleNamespace(type_code="BLOB")))

    def test_lob_empty_binary_and_temporal_are_not_normalized(self):
        stamp = datetime.datetime(2026, 1, 1, 0, 0, 0, 123456)
        source = [(FakeLOB(""), FakeLOB(b"\x00\xff"), stamp, Decimal("1.0000000000001"), " x ", None)]
        (rows, error, _), _, _ = self.execute(FakeCursor(source, width=6))
        self.assertIsNone(error)
        self.assertEqual(rows, [("", b"\x00\xff", stamp, Decimal("1.0000000000001"), " x ", None)])

    def test_no_result_and_malformed_width(self):
        for cur in (FakeCursor(description=False), FakeCursor(width=0), FakeCursor([(1, 2)], width=1)):
            with self.subTest(cursor=cur):
                (rows, error, meta), con, _ = self.execute(cur)
                self.assertIsNone(rows)
                self.assertEqual(error["kind"], "result_protocol_error")
                self.assertTrue(con.closed)
                self.assertFalse(meta["timeout"])

    def test_empty_results_use_width(self):
        self.assertTrue(self.compare([], [])[0][0])
        self.assertFalse(self.compare([], [], widths=(1, 2))[0][0])

    def test_same_errors_never_pass(self):
        driver = driver_for(FakeConnection(FakeCursor(execute_error=DriverError(942))),
                            FakeConnection(FakeCursor(execute_error=DriverError(942))))
        e = self.evaluator()
        with patch.dict(sys.modules, {"oracledb": driver}):
            passed, gold, pred = e.check_result_same()
        self.assertFalse(passed)
        self.assertTrue(gold["__uniql_execution_error__"] and pred["__uniql_execution_error__"])
        self.assertEqual(e.last_evaluation["typed_results"], {"gt": None, "pred": None})
        self.assertEqual(e.last_evaluation["comparison"]["reason"], "execution_failed")
        json.dumps(e.last_evaluation)

    def test_exact_types_and_duplicate_counts(self):
        stamp = datetime.datetime(2026, 1, 1, microsecond=1)
        cases = [(" x ", "x"), ("001", 1), ("null", None), (b"x", "x"), (True, 1),
                 (9007199254740993, 9007199254740992),
                 (Decimal("1.0000000000001"), Decimal("1.0000000000002")),
                 (stamp, stamp.replace(microsecond=2))]
        for left, right in cases:
            with self.subTest(left=left, right=right):
                self.assertFalse(self.compare([(left,)], [(right,)])[0][0])
        self.assertFalse(self.compare([(1,), (1,), (2,)], [(1,), (2,), (2,)])[0][0])
        self.assertTrue(self.compare([(Decimal("1"),)], [(1,)])[0][0])
        self.assertTrue(self.compare([(1.0,)], [(1.0 + 1e-10,)])[0][0])

    def test_ordering_is_only_gold_top_order_unless_explicit(self):
        left, right = [(1,), (2,)], [(2,), (1,)]
        cases = [(SQL, SQL + " order by value", None, True),
                 ("select * from (select value from records order by value)", SQL, None, True),
                 ("select 'order by' from dual", SQL, None, True),
                 (SQL + " order by value", SQL, None, False),
                 (SQL, SQL, "list", False),
                 (SQL + " order by value", SQL, "set", True),
                 (SQL, SQL, "subset,=,2", True)]
        for gold, pred, method, passed in cases:
            with self.subTest(gold=gold, method=method):
                result, e = self.compare(left, right, gold=gold, pred=pred, grading_method=method)
                self.assertEqual(result[0], passed)
                self.assertFalse(e.last_evaluation["official_grading"])
                self.assertEqual(e.last_evaluation["grading_method"], method)

    def test_cleanup_failure_cannot_pass_and_primary_is_preserved(self):
        con = FakeConnection(close_error=DriverError(3114, "close failed"))
        (rows, error, meta), _, _ = self.execute(connection=con)
        self.assertIsNone(rows)
        self.assertEqual(error["kind"], "session_close_error")
        self.assertFalse(meta["connection_closed"])
        con = FakeConnection(FakeCursor(execute_error=DriverError(942, "primary"),
                                        close_error=RuntimeError("cursor close")),
                             close_error=RuntimeError("connection close"))
        (rows, error, meta), _, _ = self.execute(connection=con)
        self.assertEqual(error["message"], "primary")
        self.assertEqual(error["code"], 942)
        self.assertEqual(len(meta["cleanup_errors"]), 2)

    def test_connect_cursor_fetch_lob_errors_close_owned_resources(self):
        driver = driver_for(DriverError(12541))
        with patch.dict(sys.modules, {"oracledb": driver}):
            rows, error, meta = self.evaluator()._execute_query(SQL)
        self.assertIsNone(rows)
        self.assertEqual(error["kind"], "infrastructure_error")
        self.assertEqual(meta["error_stage"], "connect")
        for con in (FakeConnection(cursor_error=RuntimeError("cursor")),
                    FakeConnection(FakeCursor(fetch_error=RuntimeError("fetch"))),
                    FakeConnection(FakeCursor([(FakeLOB(None, RuntimeError("LOB")),)]))):
            with self.subTest(connection=con):
                (rows, error, _), _, _ = self.execute(connection=con)
                self.assertIsNone(rows)
                self.assertTrue(error["__uniql_execution_error__"])
                self.assertTrue(con.closed)

    def test_native_timeout_acknowledgement_without_sleep(self):
        def expire():
            FakeTimer.latest.callback()
            raise DriverError(1013, "cancel acknowledged")
        con = FakeConnection(FakeCursor(on_query=expire))
        (rows, error, meta), _, _ = self.execute(connection=con)
        self.assertIsNone(rows)
        self.assertTrue(error["timeout"])
        self.assertTrue(meta["cancel_requested"] and meta["cancel_returned"])
        self.assertTrue(meta["native_cancel_acknowledged"])
        self.assertFalse(meta["post_cancel_health_verified"])
        self.assertEqual(con.cancel_count, 1)
        self.assertTrue(con.closed)

    def test_cancel_return_is_not_native_ack_and_cancel_errors_preserved(self):
        for failure in (None, RuntimeError("cancel failed")):
            con = FakeConnection(FakeCursor(on_query=lambda: FakeTimer.latest.callback()), cancel_error=failure)
            (rows, error, meta), _, _ = self.execute(connection=con)
            self.assertIsNone(rows)
            self.assertTrue(error["timeout"])
            self.assertFalse(meta["native_cancel_acknowledged"])
            self.assertEqual(meta["cancel_returned"], failure is None)
            if failure:
                self.assertIn("cancel_error", meta)

    def test_connect_deadline_includes_connect_elapsed(self):
        con = FakeConnection()
        driver = driver_for()
        def connect(**kwargs):
            FakeTimer.latest.callback()
            return con
        driver.connect.side_effect = connect
        with patch.dict(sys.modules, {"oracledb": driver}):
            rows, error, meta = self.evaluator()._execute_query(SQL)
        self.assertIsNone(rows)
        self.assertTrue(error["timeout"])
        self.assertEqual(meta["error_stage"], "connect")
        self.assertEqual(con.cancel_count, 1)
        self.assertTrue(con.closed)

    def test_credentials_redacted_every_error_channel(self):
        with patch.dict(os.environ, {"UNIQL_ORACLE_USER_PASSWORD": "password-secret", "UNIQL_ORACLE_DSN": "private-dsn"}):
            e = self.evaluator()
        con = FakeConnection(FakeCursor(execute_error=RuntimeError("password-secret private-dsn")),
                             close_error=RuntimeError("password-secret private-dsn"))
        with patch.dict(sys.modules, {"oracledb": driver_for(con)}):
            rows, error, meta = e._execute_query(SQL)
        serialized = json.dumps([rows, error, meta])
        self.assertNotIn("password-secret", serialized)
        self.assertNotIn("private-dsn", serialized)

    def test_total_timeout_validation_and_unbounded_positive_pair(self):
        for value in (0, -1, True, float("inf"), float("nan"), "120"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.evaluator(total_timeout=value)
        self.assertEqual(self.evaluator(total_timeout=240).total_timeout, 240)
        self.assertEqual(module.VERSION, "uniql-oracle-public-eval-v1")

    def test_native_call_timeout_full_codes_and_connection_timeout(self):
        cases = [(0, "DPY-4024", "query_timeout", "query"),
                 (0, "DPI-1067", "query_timeout", "query"),
                 (3136, "ORA-03136", "connection_timeout", "connection")]
        for code, full_code, kind, scope in cases:
            with self.subTest(full_code=full_code):
                con = FakeConnection(FakeCursor(execute_error=DriverError(code, full_code=full_code)))
                (rows, error, meta), _, _ = self.execute(connection=con)
                self.assertIsNone(rows)
                self.assertTrue(error["timeout"])
                self.assertEqual(error["kind"], kind)
                self.assertEqual(error["full_code"], full_code)
                self.assertEqual(meta["timeout_scope"], scope)
                self.assertFalse(meta["native_cancel_acknowledged"])
        detail = SimpleNamespace(code=0, message="DPI-1067: call timeout")
        self.assertEqual(module._classify_error(Exception(detail))[0], "query_timeout")

    def test_stuck_cancel_owns_both_resources_and_metadata_is_frozen(self):
        entered, release, disposed = threading.Event(), threading.Event(), threading.Event()
        class BlockingCancel(FakeConnection):
            def cancel(inner):
                inner.cancel_count += 1
                entered.set()
                release.wait(2)
            def close(inner):
                self.assertTrue(release.is_set())
                super().close()
                disposed.set()
        def expire():
            FakeTimer.latest.callback()
            self.assertTrue(entered.wait(1))
            raise DriverError(1013)
        con = BlockingCancel(FakeCursor(on_query=expire))
        e = self.evaluator(query_timeout=0.08)
        try:
            with patch.dict(sys.modules, {"oracledb": driver_for(con)}):
                rows, error, meta = e._execute_query(SQL)
            self.assertIsNone(rows)
            self.assertTrue(error["timeout"])
            self.assertTrue(meta["cleanup_deferred"])
            self.assertFalse(meta["complete"])
            self.assertEqual(meta["resource_health"], "unknown")
            self.assertFalse(con.closed or con.cur.closed)
            frozen = json.dumps(meta, sort_keys=True)
        finally:
            release.set()
        self.assertTrue(disposed.wait(1))
        self.assertTrue(con.cur.closed)
        self.assertEqual(json.dumps(meta, sort_keys=True), frozen)
        self.assertFalse(meta["strict_hard_deadline"])

    def test_blocking_close_is_deferred_not_query_timeout_and_preserves_primary(self):
        for primary in (None, DriverError(942, "primary")):
            entered, release, disposed = threading.Event(), threading.Event(), threading.Event()
            class BlockingClose(FakeConnection):
                def close(inner):
                    entered.set()
                    release.wait(2)
                    super().close()
                    disposed.set()
            con = BlockingClose(FakeCursor(execute_error=primary))
            e = self.evaluator(query_timeout=0.06)
            try:
                with patch.dict(sys.modules, {"oracledb": driver_for(con)}):
                    rows, error, meta = e._execute_query(SQL)
                self.assertTrue(entered.is_set())
                self.assertIsNone(rows)
                self.assertFalse(error["timeout"])
                self.assertTrue(meta["cleanup_timeout"] and meta["cleanup_deferred"])
                self.assertFalse(meta["complete"])
                self.assertEqual(error["kind"], "query_error" if primary else "session_close_deadline")
                self.assertEqual(error["code"], 942 if primary else None)
                if primary:
                    self.assertEqual(error["message"], "primary")
                frozen = json.dumps(meta, sort_keys=True)
            finally:
                release.set()
            self.assertTrue(disposed.wait(1))
            self.assertEqual(json.dumps(meta, sort_keys=True), frozen)

    def test_pair_budget_exhausted_by_gold_cleanup_does_not_connect_prediction(self):
        release, disposed = threading.Event(), threading.Event()
        class SlowClose(FakeConnection):
            def close(inner):
                release.wait(2)
                super().close()
                disposed.set()
        con = SlowClose(FakeCursor([(1,)]))
        driver = driver_for(con)
        e = self.evaluator(query_timeout=120, total_timeout=0.06)
        try:
            with patch.dict(sys.modules, {"oracledb": driver}):
                passed, gold, pred = e.check_result_same()
            self.assertFalse(passed)
            self.assertEqual(gold["kind"], "session_close_deadline")
            self.assertEqual(pred["kind"], "prior_session_unresolved")
            self.assertFalse(pred["timeout"])
            self.assertFalse(e.last_evaluation["pred"]["dispatched"])
            self.assertIsNone(e.last_evaluation["pred"]["code"])
            self.assertEqual(driver.connect.call_count, 1)
            self.assertIsNone(e._pair_deadline)
            self.assertTrue(e.last_evaluation["pair_timeout"])
        finally:
            release.set()
        self.assertTrue(disposed.wait(1))

    def test_unresolved_gold_cancel_blocks_pred_with_pair_budget_remaining(self):
        entered, release, disposed = threading.Event(), threading.Event(), threading.Event()
        class BlockingCancel(FakeConnection):
            def cancel(inner):
                inner.cancel_count += 1
                entered.set()
                release.wait(2)
            def close(inner):
                super().close()
                disposed.set()
        def expire():
            FakeTimer.latest.callback()
            self.assertTrue(entered.wait(1))
            raise DriverError(1013)
        con = BlockingCancel(FakeCursor(on_query=expire))
        driver = driver_for(con)
        e = self.evaluator(query_timeout=0.04, total_timeout=0.2)
        try:
            with patch.dict(sys.modules, {"oracledb": driver}):
                passed, gold, pred = e.check_result_same()
            self.assertFalse(passed)
            self.assertTrue(gold["timeout"])
            self.assertTrue(pred["__uniql_execution_error__"])
            self.assertEqual(pred["kind"], "prior_session_unresolved")
            pred_meta = e.last_evaluation["pred"]
            self.assertFalse(pred_meta["dispatched"] or pred_meta["complete"])
            self.assertIsNone(pred_meta["column_count"])
            self.assertFalse(e.last_evaluation["pair_timeout"])
            self.assertEqual(driver.connect.call_count, 1)
            self.assertIsNone(e._pair_deadline)
            self.assertFalse(con.closed or con.cur.closed)
            frozen = json.dumps(e.last_evaluation, sort_keys=True)
        finally:
            release.set()
        self.assertTrue(disposed.wait(1))
        self.assertEqual(json.dumps(e.last_evaluation, sort_keys=True), frozen)

    def test_disposed_gold_error_and_nondispatch_admission_allow_prediction(self):
        for gold_sql, connections, expected_connects in (
                (SQL, [FakeConnection(FakeCursor(execute_error=DriverError(942))),
                       FakeConnection(FakeCursor([(1,)]))], 2),
                ("delete from records", [FakeConnection(FakeCursor([(1,)]))], 1)):
            with self.subTest(gold_sql=gold_sql):
                e = self.evaluator(gold=gold_sql)
                driver = driver_for(*connections)
                with patch.dict(sys.modules, {"oracledb": driver}):
                    passed, _, pred = e.check_result_same()
                self.assertFalse(passed)
                self.assertEqual(pred, [(1,)])
                self.assertTrue(e.last_evaluation["pred"]["dispatched"])
                self.assertEqual(driver.connect.call_count, expected_connects)
                self.assertIsNone(e._pair_deadline)

    def test_gold_close_error_blocks_prediction(self):
        con = FakeConnection(FakeCursor([(1,)]), close_error=RuntimeError("close failed"))
        driver = driver_for(con)
        e = self.evaluator()
        with patch.dict(sys.modules, {"oracledb": driver}):
            passed, gold, pred = e.check_result_same()
        self.assertFalse(passed)
        self.assertEqual(gold["kind"], "session_close_error")
        self.assertEqual(pred["kind"], "prior_session_unresolved")
        self.assertEqual(driver.connect.call_count, 1)
        self.assertIsNone(e._pair_deadline)

    def test_pair_remaining_budget_caps_each_side_without_signature_change(self):
        clock = [10.0]
        class AdvancingClose(FakeConnection):
            def close(inner):
                clock[0] += 2
                super().close()
        con1 = AdvancingClose(FakeCursor([(1,)]))
        con2 = FakeConnection(FakeCursor([(1,)]))
        driver = driver_for(con1, con2)
        e = self.evaluator(query_timeout=120, total_timeout=5)
        with patch.object(module.time, "monotonic", side_effect=lambda: clock[0]), \
                patch.dict(sys.modules, {"oracledb": driver}):
            self.assertTrue(e.check_result_same()[0])
        self.assertEqual(e.last_evaluation["gt"]["effective_timeout"], 5)
        self.assertEqual(e.last_evaluation["pred"]["effective_timeout"], 3)
        self.assertEqual(driver.connect.call_args.kwargs["tcp_connect_timeout"], 3)
        self.assertTrue(e.last_evaluation["gt"]["complete"])
        self.assertTrue(e.last_evaluation["pred"]["complete"])

    def test_real_timer_cancels_blocking_execute_from_separate_thread(self):
        cancelled, disposed = threading.Event(), threading.Event()
        main_thread = threading.get_ident()
        class NativeConnection(FakeConnection):
            def cancel(inner):
                self.assertNotEqual(threading.get_ident(), main_thread)
                inner.cancel_count += 1
                cancelled.set()
            def close(inner):
                self.assertNotEqual(threading.get_ident(), main_thread)
                super().close()
                disposed.set()
        def blocking_query():
            self.assertTrue(cancelled.wait(1))
            raise DriverError(1013)
        con = NativeConnection(FakeCursor(on_query=blocking_query))
        e = self.evaluator(query_timeout=0.05)
        with patch.object(module.threading, "Timer", REAL_TIMER), \
                patch.dict(sys.modules, {"oracledb": driver_for(con)}):
            rows, error, meta = e._execute_query(SQL)
        self.assertIsNone(rows)
        self.assertTrue(error["timeout"])
        self.assertTrue(meta["native_cancel_acknowledged"])
        self.assertTrue(disposed.wait(1))
        self.assertEqual(con.cancel_count, 1)
        self.assertFalse(meta["strict_hard_deadline"])

    def test_successful_query_late_close_is_nonquery_deadline(self):
        clock = [0.0]
        class LateClose(FakeConnection):
            def close(inner):
                clock[0] = 121.0
                super().close()
        con = LateClose(FakeCursor([(1,)]))
        with patch.object(module.time, "monotonic", side_effect=lambda: clock[0]):
            (rows, error, meta), _, _ = self.execute(connection=con)
        self.assertIsNone(rows)
        self.assertEqual(error["kind"], "session_close_deadline")
        self.assertFalse(error["timeout"])
        self.assertEqual(error["timeout_scope"], "cleanup")
        self.assertTrue(meta["cleanup_timeout"])
        self.assertFalse(meta["complete"])

    def test_cleanup_over_budget_after_completion_retains_query_error(self):
        clock = [0.0]
        class LateClose(FakeConnection):
            def close(inner):
                clock[0] = 121.0
                super().close()
        con = LateClose(FakeCursor(execute_error=DriverError(942, "original")))
        with patch.object(module.time, "monotonic", side_effect=lambda: clock[0]):
            (rows, error, meta), _, _ = self.execute(connection=con)
        self.assertIsNone(rows)
        self.assertEqual(error["kind"], "query_error")
        self.assertEqual(error["code"], 942)
        self.assertEqual(error["message"], "original")
        self.assertFalse(error["timeout"])
        self.assertTrue(meta["cleanup_timeout"])
        self.assertFalse(meta["complete"])

    def test_last_evaluation_replaced_and_unsupported_values_fail_closed(self):
        e = self.evaluator()
        drivers = driver_for(FakeConnection(FakeCursor([(1,)])), FakeConnection(FakeCursor([(1,)])),
                             FakeConnection(FakeCursor([(object(),)])), FakeConnection(FakeCursor([(object(),)])))
        with patch.dict(sys.modules, {"oracledb": drivers}):
            self.assertTrue(e.check_result_same()[0])
            previous = e.last_evaluation
            self.assertFalse(e.check_result_same()[0])
        self.assertIsNot(e.last_evaluation, previous)
        json.dumps(e.last_evaluation)


if __name__ == "__main__":
    unittest.main()
