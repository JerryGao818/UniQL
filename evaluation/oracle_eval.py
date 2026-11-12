"""Public Oracle EX adapter: original SQL, exact driver values, owned sessions.

This is project EX, not official Platinum grading or a runtime acceptance gate.
Native cancellation acknowledgements do not prove post-cancel server health.
"""
from copy import deepcopy
from decimal import Decimal
import importlib
import math
import os
from pathlib import Path
import re
import threading
import time

import sqlglot
from sqlglot import exp
from sqlglot.dialects.oracle import Oracle
from sqlglot.tokens import TokenType

VERSION = "uniql-oracle-public-eval-v1"
SESSION_SQL = (
    "ALTER SESSION SET NLS_NUMERIC_CHARACTERS='.,'",
    "ALTER SESSION SET NLS_DATE_FORMAT='YYYY-MM-DD'",
    "ALTER SESSION SET NLS_TIMESTAMP_FORMAT='YYYY-MM-DD HH24:MI:SS.FF9'",
    "ALTER SESSION SET NLS_SORT=BINARY",
    "ALTER SESSION SET NLS_COMP=BINARY",
    "ALTER SESSION SET TIME_ZONE='+00:00'",
)


def _comparison_module():
    if __package__:
        return importlib.import_module(".oracle_ex", __package__)
    return importlib.import_module("oracle_ex")


def _classify_error(error):
    detail = error.args[0] if error.args else None
    code = getattr(detail, "code", None)
    full_code = getattr(detail, "full_code", None)
    if not full_code:
        match = re.search(r"\b(?:DPY|DPI|ORA)-\d+\b", str(getattr(detail, "message", error)))
        full_code = match.group() if match else None
    if full_code in {"DPY-4024", "DPI-1067"}:
        return "query_timeout", code, full_code
    # ORA-03136 is inbound connection authentication timeout, not a call cancel.
    if code == 3136 or full_code == "ORA-03136":
        return "connection_timeout", code, full_code
    if not code or str(full_code).startswith(("DPY-", "DPI-")):
        return "driver_error", code, full_code
    if code == 1013:
        return "query_cancelled", code, full_code
    if code in {1017, 1031}:
        return "auth_or_privilege_error", code, full_code
    if code in {1652, 1653, 2391, 4030, 4031, 12954}:
        return "resource_blocked", code, full_code
    if code in {600, 1466, 1555, 3113, 3114, 3135, 4021, 7445, 12154,
                12170, 12514, 12516, 12518, 12520, 12528, 12537, 12541,
                12545, 12547, 12560, 12571}:
        return "infrastructure_error", code, full_code
    return "query_error", code, full_code


class OracleEvaluater:
    """Keep the historical misspelled class and three-value result contract."""

    def __init__(self, db_path, oracle_gt, oracle_pred, *, query_timeout=120,
                 grading_method=None, total_timeout=None):
        if (isinstance(query_timeout, bool) or not isinstance(query_timeout, (int, float))
                or not math.isfinite(query_timeout) or not 0 < query_timeout <= 120):
            raise ValueError("query_timeout must be positive and at most 120 seconds")
        if total_timeout is not None and (
                isinstance(total_timeout, bool) or not isinstance(total_timeout, (int, float))
                or not math.isfinite(total_timeout) or total_timeout <= 0):
            raise ValueError("total_timeout must be finite and positive")
        self.total_timeout = float(total_timeout) if total_timeout is not None else None
        self._pair_deadline = None
        self.db_path = db_path
        self.oracle_gt = oracle_gt
        self.oracle_pred = oracle_pred
        self.query_timeout = float(query_timeout)
        self.grading_method = grading_method
        db_id = Path(db_path).stem
        configured_user = os.getenv("UNIQL_ORACLE_USER")
        if configured_user is None:
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_$#]{0,127}", db_id, flags=re.ASCII):
                raise ValueError("db_id must be a simple Oracle username, or set UNIQL_ORACLE_USER")
            configured_user = db_id.upper()
        if not configured_user:
            raise ValueError("Oracle username must not be empty")
        # Explicit usernames are authentication values, never interpolated into SQL.
        self.oracle_user = configured_user
        self.admin_user = os.getenv("UNIQL_ORACLE_ADMIN_USER", "SYSTEM")
        self.admin_pass = os.getenv("UNIQL_ORACLE_USER_PASSWORD",
                                    os.getenv("UNIQL_ORACLE_PASSWORD", "<ORACLE_PASSWORD>"))
        self.oracle_dsn = os.getenv("UNIQL_ORACLE_DSN", "localhost:1521/FREEPDB1")
        self.last_evaluation = None

    def _safe_message(self, error):
        message = str(error)
        for secret in (self.admin_pass, self.oracle_dsn):
            if secret:
                message = message.replace(secret, "[REDACTED]")
        return re.sub(r"[\x00-\x1f]", " ", message)[:1000]

    def clean_sql(self, sql):
        """Remove only one terminating punctuation token, preserving every other byte."""
        if not isinstance(sql, str):
            raise ValueError("SQL must be text")
        tokens = Oracle().tokenize(sql)
        semicolons = [token for token in tokens if token.token_type == TokenType.SEMICOLON]
        if semicolons:
            if len(semicolons) != 1 or semicolons[0] is not tokens[-1]:
                raise ValueError("Expected exactly one Oracle query")
            token = semicolons[0]
            return sql[:token.start] + sql[token.end + 1:]
        return sql

    def _validate_query(self, sql):
        nodes = [node for node in sqlglot.parse(sql, read="oracle") if node is not None]
        if len(nodes) != 1 or not isinstance(nodes[0], exp.Query) or not nodes[0].find(exp.Select):
            raise ValueError("Expected exactly one Oracle SELECT/WITH query")
        tree = nodes[0]
        for forbidden in (exp.DML, exp.DDL, exp.Into, exp.Lock, exp.Command, exp.Hint):
            if tree.find(forbidden):
                raise ValueError("Non-read-only Oracle query")
        return tree

    @staticmethod
    def number_output_handler(driver):
        def handler(cursor, metadata):
            if metadata.type_code == driver.DB_TYPE_NUMBER:
                return cursor.var(driver.DB_TYPE_VARCHAR, size=172,
                                  arraysize=cursor.arraysize, outconverter=Decimal)
            return None
        return handler

    def _error_payload(self, error, meta):
        return {"__uniql_execution_error__": True, "engine": "oracle",
                "message": self._safe_message(error), "code": meta.get("code"),
                "timeout": bool(meta.get("timeout")), "kind": meta.get("kind", "driver_error"),
                "full_code": meta.get("full_code"), "timeout_scope": meta.get("timeout_scope"),
                "cleanup_timeout": bool(meta.get("cleanup_timeout"))}

    def _execute_query(self, sql):
        """Owned native deadline, not a strictly hard Python wall-time guarantee.

        Driver execute/connect may still block despite call_timeout. Only the
        lifecycle worker calls cancel/close; it retains both resources if cancel
        or close is pending. The caller never closes underneath native cancel.
        """
        started = time.monotonic()
        deadline = started + self.query_timeout
        if self._pair_deadline is not None:
            deadline = min(deadline, self._pair_deadline)
        budget = max(0.0, deadline - started)
        meta = {"adapter_version": VERSION, "column_count": None, "columns": None,
                "timeout": False, "code": None, "full_code": None, "kind": None,
                "read_only_confirmed": False, "session_sql": list(SESSION_SQL),
                "cancel_requested": False, "cancel_returned": False,
                "native_cancel_acknowledged": False, "cleanup_errors": [],
                "connection_closed": False, "cursor_closed": False,
                "post_cancel_health_verified": False, "complete": False,
                "cleanup_deferred": False, "cleanup_timeout": False,
                "resource_health": "unknown", "strict_hard_deadline": False,
                "effective_timeout": budget, "dispatched": False, "timeout_scope": None}
        connection = cursor = timer = worker = None
        rows = error = None
        expired = threading.Event()
        wake = threading.Event()
        connect_done = threading.Event()
        query_done = threading.Event()
        cleanup_done = threading.Event()
        lock = threading.Lock()
        cleanup_failures = []

        def request_cancel():
            # This callback and deadline checks never execute native driver calls.
            if not query_done.is_set():
                expired.set()
            wake.set()

        def lifecycle():
            wake.wait()
            connect_done.wait()
            if expired.is_set() and connection is not None:
                with lock:
                    meta["cancel_requested"] = True
                try:
                    connection.cancel()
                    with lock:
                        meta["cancel_returned"] = True
                except Exception as exc:
                    with lock:
                        meta["cancel_error"] = self._safe_message(exc)
            # Even when cancellation hangs, this task owns later disposal.
            query_done.wait()
            for resource, label in ((cursor, "cursor"), (connection, "connection")):
                if resource is not None:
                    try:
                        resource.close()
                        with lock:
                            meta[label + "_closed"] = True
                    except Exception as exc:
                        with lock:
                            cleanup_failures.append(exc)
                            meta["cleanup_errors"].append({"resource": label,
                                                           "message": self._safe_message(exc)})
            cleanup_done.set()

        def check_deadline():
            if expired.is_set() or time.monotonic() >= deadline:
                request_cancel()
                raise TimeoutError("Oracle query native deadline exceeded")
            if connection is not None:
                connection.call_timeout = max(1, int((deadline - time.monotonic()) * 1000))

        stage = "admission"
        try:
            if budget <= 0:
                stage = "pre_dispatch"
                raise TimeoutError("Oracle pair budget exhausted before dispatch")
            sql = self.clean_sql(sql)
            self._validate_query(sql)
            stage = "driver_import"
            driver = importlib.import_module("oracledb")
            check_deadline()
            stage = "connect"
            worker = threading.Thread(target=lifecycle, name="uniql-oracle-lifecycle", daemon=True)
            worker.start()
            timer = threading.Timer(max(0, deadline - time.monotonic()), request_cancel)
            timer.daemon = True
            timer.start()
            meta["dispatched"] = True
            try:
                connection = driver.connect(user=self.oracle_user, password=self.admin_pass,
                                            dsn=self.oracle_dsn,
                                            tcp_connect_timeout=min(budget, 15), retry_count=0)
            finally:
                connect_done.set()
            check_deadline()
            connection.autocommit = False
            connection.outputtypehandler = self.number_output_handler(driver)
            cursor = connection.cursor()
            cursor.arraysize = 1000
            stage = "session"
            for statement in SESSION_SQL:
                check_deadline()
                cursor.execute(statement)
            check_deadline()
            cursor.execute("SET TRANSACTION READ ONLY")
            meta["read_only_confirmed"] = True
            stage = "query"
            check_deadline()
            cursor.execute(sql)
            description = cursor.description
            if not description:
                raise ValueError("Query did not return a positive-width result set")
            meta["column_count"] = len(description)
            meta["columns"] = [{"name": str(item[0]),
                                "type": str(item[1]) if len(item) > 1 else "UNKNOWN"}
                               for item in description]
            stage = "fetch"
            rows = []
            while True:
                check_deadline()
                batch = cursor.fetchmany(cursor.arraysize)
                if not batch:
                    break
                for row in batch:
                    check_deadline()
                    if not isinstance(row, (list, tuple)) or len(row) != meta["column_count"]:
                        raise ValueError("Row width disagrees with cursor metadata")
                    values = tuple(value.read() if isinstance(value, driver.LOB) else value
                                   for value in row)
                    check_deadline()
                    rows.append(values)
            check_deadline()
        except Exception as exc:
            error = exc
            kind, code, full_code = _classify_error(exc)
            meta.update(kind="admission_error" if stage == "admission" else kind,
                        code=code, full_code=full_code, error_stage=stage,
                        native_cancel_acknowledged=code == 1013)
            is_timeout = (kind in {"query_timeout", "connection_timeout"}
                          or isinstance(exc, TimeoutError) or expired.is_set()
                          or stage != "admission" and time.monotonic() >= deadline)
            if is_timeout:
                meta.update(timeout=True, kind=("pair_budget_exhausted" if stage == "pre_dispatch"
                                               else kind if kind == "connection_timeout" else "query_timeout"),
                            native_cancel_acknowledged=code == 1013,
                            timeout_scope="pair" if stage == "pre_dispatch" else
                            "connection" if kind == "connection_timeout" else "query")
                request_cancel()
            elif stage in {"query", "fetch"} and isinstance(exc, ValueError):
                meta["kind"] = "result_protocol_error"
        finally:
            # Close is never presumed bounded; run it only in the owned worker.
            query_done.set()
            connect_done.set()
            wake.set()
            if worker is not None:
                cleanup_done.wait(timeout=max(0.0, deadline - time.monotonic()))
            if timer is not None:
                timer.cancel()
                timer.join(timeout=max(0.0, deadline - time.monotonic()))
            with lock:
                pending = worker is not None and not cleanup_done.is_set()
                cleanup_over_budget = worker is not None and time.monotonic() >= deadline
                meta.update(cleanup_deferred=pending, cleanup_timeout=cleanup_over_budget,
                            cancel_thread_alive=pending,
                            elapsed_sec=time.monotonic() - started)
                if cleanup_over_budget:
                    meta["cleanup_errors"].append({"resource": "lifecycle",
                                                   "kind": "cleanup_timeout",
                                                   "message": "Session disposal exceeded available budget"})
                # Preserve the query's original error/code/kind through disposal.
                if error is None and (pending or cleanup_over_budget):
                    error = TimeoutError("Oracle session close deadline exceeded")
                    meta.update(kind="session_close_deadline", error_stage="cleanup",
                                timeout=False, timeout_scope="cleanup")
                elif error is None and cleanup_failures:
                    error = cleanup_failures[0]
                    _, code, full_code = _classify_error(error)
                    meta.update(kind="session_close_error", error_stage="cleanup",
                                code=code, full_code=full_code)
                meta["complete"] = (error is None and not pending and not cleanup_over_budget
                                    and meta["connection_closed"] and meta["cursor_closed"])
                meta["resource_health"] = ("disposed" if not pending and meta["connection_closed"]
                                           else "unknown")
                # Worker may finish after return; evidence must remain immutable.
                frozen_meta = deepcopy(meta)
        if error is not None:
            return None, self._error_payload(error, frozen_meta), frozen_meta
        return rows, None, frozen_meta

    def oracle_query(self, query):
        """Legacy convenience wrapper; failures are structured, never fake rows."""
        rows, error, _ = self._execute_query(query)
        return error if error is not None else rows

    def check_result_same(self):
        pair_started = time.monotonic()
        self._pair_deadline = (pair_started + self.total_timeout
                               if self.total_timeout is not None else None)
        self.last_evaluation = None
        comparison = _comparison_module()
        gold_top_order = False
        try:
            tree = self._validate_query(self.clean_sql(self.oracle_gt))
            while isinstance(tree, exp.Subquery):
                tree = tree.this
            gold_top_order = tree.args.get("order") is not None
        except Exception:
            # Execution records the admission failure; it must never become a pass.
            pass
        if self.grading_method is None:
            effective_grading = "list" if gold_top_order else None
            ordering_rule = "gold_top_level_order_by" if gold_top_order else "default_project_bag"
        else:
            effective_grading = self.grading_method
            ordering_rule = "grading_method_list" if self.grading_method == "list" else "explicit_grading_project_bag"
        try:
            gt_rows, gt_error, gt_meta = self._execute_query(self.oracle_gt)
            prior_unresolved = gt_meta.get("dispatched", False) and (
                gt_meta.get("cleanup_deferred", False)
                or gt_meta.get("resource_health") != "disposed"
                or not gt_meta.get("connection_closed", False)
                or bool(gt_meta.get("cleanup_errors")))
            if prior_unresolved:
                # Do not overlap a new session with unresolved owned native work.
                # This is a stable non-dispatch record, not a second SQL timeout.
                pred_rows = None
                pred_meta = {
                    "adapter_version": VERSION, "column_count": None, "columns": None,
                    "kind": "prior_session_unresolved", "code": None, "full_code": None,
                    "timeout": False, "timeout_scope": None, "error_stage": "pre_dispatch",
                    "dispatched": False, "complete": False, "read_only_confirmed": False,
                    "session_sql": list(SESSION_SQL), "cancel_requested": False,
                    "cancel_returned": False, "native_cancel_acknowledged": False,
                    "cleanup_deferred": False, "cleanup_timeout": False, "cleanup_errors": [],
                    "connection_closed": False, "cursor_closed": False,
                    "resource_health": "not_created", "post_cancel_health_verified": False,
                    "strict_hard_deadline": False, "effective_timeout": 0.0, "elapsed_sec": 0.0,
                    "prior_session": {"cleanup_deferred": gt_meta.get("cleanup_deferred", False),
                                      "resource_health": gt_meta.get("resource_health"),
                                      "connection_closed": gt_meta.get("connection_closed", False),
                                      "cleanup_errors": deepcopy(gt_meta.get("cleanup_errors", []))}}
                pred_error = self._error_payload(
                    RuntimeError("Prediction not dispatched: prior Oracle session unresolved"), pred_meta)
            else:
                pred_rows, pred_error, pred_meta = self._execute_query(self.oracle_pred)
        finally:
            self._pair_deadline = None
        record = comparison.verify_results_oracle(
            gt_rows, pred_rows, source_error=gt_error, target_error=pred_error,
            source_columns=gt_meta["column_count"], target_columns=pred_meta["column_count"],
            grading_method=effective_grading)
        typed_results = {}
        for side, rows in (("gt", gt_rows), ("pred", pred_rows)):
            try:
                typed_results[side] = comparison.encode_result(rows)
            except Exception as exc:
                typed_results[side] = None
                record.update(passed=False, reason="typed_evidence_encoding_failed")
                record[side + "_encoding_error"] = self._safe_message(exc)
        pair_elapsed = time.monotonic() - pair_started
        pair_timeout = self.total_timeout is not None and pair_elapsed >= self.total_timeout
        if pair_timeout and record["passed"]:
            record.update(passed=False, reason="pair_budget_exhausted")
        self.last_evaluation = {
            "version": VERSION, "comparison_policy": comparison.comparison_policy(),
            "comparison": record, "grading_method": self.grading_method,
            "effective_grading_method": effective_grading, "ordering_rule": ordering_rule,
            "official_grading": False, "gold_top_level_order_by": gold_top_order,
            "gt": gt_meta, "pred": pred_meta, "total_timeout": self.total_timeout,
            "pair_elapsed_sec": pair_elapsed, "pair_timeout": pair_timeout,
            "typed_results": typed_results}
        return bool(record["passed"]), (gt_error if gt_error is not None else gt_rows), (pred_error if pred_error is not None else pred_rows)


OracleEvaluator = OracleEvaluater
