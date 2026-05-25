import argparse
import socket
import time
from pathlib import Path

import pymysql
import sys

REPO_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR))

from sqlite_dataset_utils import (  # noqa: E402
    clean_identifier,
    fetch_all_rows,
    get_columns,
    get_tables,
    infer_declared_kind,
    list_bird_databases,
    map_sqlite_to_doris_type,
    max_text_lengths,
    normalize_for_doris,
    sqlite_path,
    write_name_map,
)

import subprocess


COMPOSE_FILE = PROJECT_DIR / "docker-compose.yml"
NAME_MAP_DIR = PROJECT_DIR / "results" / "name_map"
HOST = "127.0.0.1"
PORT = 9030
FE_HTTP_PORT = 8030
USER = "root"
PASSWORD = ""
FE_CONTAINER = "uniql-doris-fe"
BE_CONTAINER = "uniql-doris-be"
BE_HEARTBEAT_ADDR = "172.30.0.3:9050"
DORIS_DEFAULT_BATCH_SIZE = 50
DORIS_MIN_BATCH_SIZE = 1
RETRYABLE_INSERT_MARKERS = (
    "mem_alloc_failed",
    "failed to get query fragments context",
    "query may be timeout or be cancelled",
    "internal_error",
    "exceed limit",
    "less than low water mark",
    "timeout",
    "cancelled",
)
TRANSIENT_PULL_ERRORS = (
    "unexpected eof",
    " eof",
    "short read",
    "failed to copy",
    "tls handshake timeout",
    "connection reset by peer",
    "context canceled",
    "i/o timeout",
    "temporary error",
)


def run(cmd, cwd=None, check=True, capture_output=False):
    return subprocess.run(cmd, cwd=cwd, check=check, capture_output=capture_output, text=True)


def docker_compose(*args, capture_output=False):
    return run(["docker", "compose", "-f", str(COMPOSE_FILE), *args], cwd=PROJECT_DIR, capture_output=capture_output)


def container_status(container: str) -> str:
    result = run(["docker", "inspect", "-f", "{{.State.Status}}", container], check=False, capture_output=True)
    if result.returncode != 0:
        return "missing"
    return result.stdout.strip() or "unknown"


def container_logs(container: str, tail: int = 120) -> str:
    result = run(["docker", "logs", "--tail", str(tail), container], check=False, capture_output=True)
    return ((result.stdout or "") + "\n" + (result.stderr or "")).strip()


def cleanup_doris_runtime(remove_images: bool = False):
    run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "down", "--remove-orphans"],
        cwd=PROJECT_DIR,
        check=False,
        capture_output=True,
    )
    if remove_images:
        run(
            ["docker", "image", "rm", "-f", "apache/doris:fe-2.1.11", "apache/doris:be-2.1.11"],
            check=False,
            capture_output=True,
        )


def is_transient_pull_error(exc: subprocess.CalledProcessError) -> bool:
    text = ((exc.stdout or "") + "\n" + (exc.stderr or "")).lower()
    return any(marker in text for marker in TRANSIENT_PULL_ERRORS)


def compose_pull_with_retry(retries: int = 5, sleep_sec: int = 10):
    for attempt in range(1, retries + 1):
        print(f"[INFO] pulling Doris images (attempt {attempt}/{retries})")
        result = run(
            ["docker", "compose", "-f", str(COMPOSE_FILE), "pull", "fe", "be"],
            cwd=PROJECT_DIR,
            check=False,
            capture_output=False,
        )
        if result.returncode == 0:
            return
        if attempt == retries:
            raise subprocess.CalledProcessError(result.returncode, result.args)
        print("[WARN] Doris image pull failed; retrying after a short wait")
        time.sleep(sleep_sec * attempt)


def compose_up(retries: int = 3, sleep_sec: int = 10):
    compose_pull_with_retry()
    for attempt in range(1, retries + 1):
        result = run(
            ["docker", "compose", "-f", str(COMPOSE_FILE), "up", "-d"],
            cwd=PROJECT_DIR,
            check=False,
            capture_output=False,
        )
        if result.returncode == 0:
            return
        if attempt == 1:
            print("[WARN] Doris startup failed; cleaning Doris runtime and image cache before retry")
            cleanup_doris_runtime(remove_images=True)
            compose_pull_with_retry(retries=retries, sleep_sec=sleep_sec)
        else:
            cleanup_doris_runtime(remove_images=False)
        if attempt == retries:
            raise subprocess.CalledProcessError(result.returncode, result.args)
        print("[WARN] transient compose failure detected during Doris startup, retrying")
        time.sleep(sleep_sec * attempt)


def compose_down():
    cleanup_doris_runtime(remove_images=False)


def connect(database=None):
    kwargs = {
        "host": HOST,
        "port": PORT,
        "user": USER,
        "password": PASSWORD,
        "charset": "utf8mb4",
        "autocommit": False,
        "connect_timeout": 5,
        "read_timeout": 5,
        "write_timeout": 5,
    }
    if database:
        kwargs["database"] = database
    return pymysql.connect(**kwargs)


def wait_for_fe(timeout_sec=600):
    print("[INFO] waiting for Doris FE to become ready")
    deadline = time.time() + timeout_sec
    last_error = ""
    while time.time() < deadline:
        fe_status = container_status(FE_CONTAINER)
        be_status = container_status(BE_CONTAINER)
        if fe_status == "exited":
            raise RuntimeError(f"Doris FE exited unexpectedly.\n\n{container_logs(FE_CONTAINER)}")
        if be_status == "exited":
            raise RuntimeError(f"Doris BE exited unexpectedly while waiting for FE.\n\n{container_logs(BE_CONTAINER)}")
        try:
            with socket.create_connection((HOST, PORT), timeout=5):
                pass
            with socket.create_connection((HOST, FE_HTTP_PORT), timeout=5):
                pass
            print("[INFO] Doris FE is ready")
            return
        except Exception as exc:
            last_error = str(exc)
            time.sleep(5)
    raise TimeoutError(
        "Doris FE did not become ready in time"
        + (f". Last error: {last_error}" if last_error else "")
        + f"\n\nFE logs:\n{container_logs(FE_CONTAINER, tail=80)}"
    )


def ensure_backend(timeout_sec=600):
    print("[INFO] ensuring Doris BE is registered and alive")
    deadline = time.time() + timeout_sec
    last_error = ""
    while time.time() < deadline:
        be_status = container_status(BE_CONTAINER)
        fe_status = container_status(FE_CONTAINER)
        if fe_status == "exited":
            raise RuntimeError(f"Doris FE exited unexpectedly.\n\n{container_logs(FE_CONTAINER)}")
        if be_status == "exited":
            raise RuntimeError(f"Doris BE exited unexpectedly.\n\n{container_logs(BE_CONTAINER)}")
        try:
            conn = connect()
            with conn.cursor() as cursor:
                cursor.execute("SHOW BACKENDS")
                rows = cursor.fetchall()
                columns = [col[0].lower() for col in cursor.description]
                row_dicts = [dict(zip(columns, row)) for row in rows]
                if row_dicts and any(str(row.get("alive", "")).lower() in {"true", "1"} for row in row_dicts):
                    conn.close()
                    print("[INFO] Doris BE is alive")
                    return
                try:
                    cursor.execute(f'ALTER SYSTEM ADD BACKEND "{BE_HEARTBEAT_ADDR}"')
                    conn.commit()
                except Exception:
                    conn.rollback()
            conn.close()
        except Exception as exc:
            last_error = str(exc)
        time.sleep(5)
    raise TimeoutError(
        "Doris BE did not become alive in time"
        + (f". Last error: {last_error}" if last_error else "")
        + f"\n\nBE logs:\n{container_logs(BE_CONTAINER, tail=120)}"
    )


def build_create_table_sql(db_name: str, table_name: str, columns: list[dict], text_lengths: dict[str, int]) -> str:
    safe_table = clean_identifier(table_name)
    key_column = columns[0]["clean_name"]
    lines = []
    for index, column in enumerate(columns):
        declared_type = column["declared_type"]
        original_name = column["original_name"]
        key_col = index == 0
        dtype = map_sqlite_to_doris_type(declared_type, text_lengths.get(original_name, 0), key_column=key_col)
        lines.append(f"  `{column['clean_name']}` {dtype}")
    column_sql = ",\n".join(lines)
    return f"""
    CREATE TABLE `{db_name}`.`{safe_table}` (
    {column_sql}
    )
    ENGINE=OLAP
    DUPLICATE KEY(`{key_column}`)
    DISTRIBUTED BY HASH(`{key_column}`) BUCKETS 1
    PROPERTIES (
      "replication_num" = "1"
    )
    """


def _is_retryable_insert_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in RETRYABLE_INSERT_MARKERS)


def _insert_single_row(conn, insert_sql: str, row: tuple, db_name: str, table_label: str, max_retries: int = 5):
    for attempt in range(1, max_retries + 1):
        try:
            with conn.cursor() as cursor:
                cursor.execute(insert_sql, row)
            conn.commit()
            return conn
        except Exception as exc:
            conn.rollback()
            if not _is_retryable_insert_error(exc) or attempt == max_retries:
                raise
            print(
                f"[WARN] Doris row insert hit resource pressure for {db_name}.{table_label}; "
                f"retrying ({attempt}/{max_retries})"
            )
            try:
                conn.close()
            except Exception:
                pass
            time.sleep(min(2 * attempt, 10))
            conn = connect(database=db_name)
    return conn


def insert_rows(
    conn,
    db_name: str,
    table_name: str,
    columns: list[dict],
    rows: list[tuple],
    batch_size: int = DORIS_DEFAULT_BATCH_SIZE,
):
    if not rows:
        return conn
    placeholders = ", ".join(["%s"] * len(columns))
    safe_table = clean_identifier(table_name)
    insert_sql = f"INSERT INTO `{db_name}`.`{safe_table}` VALUES ({placeholders})"
    converted_rows = [
        tuple(normalize_for_doris(value, columns[idx]["declared_type"]) for idx, value in enumerate(row))
        for row in rows
    ]
    current_batch_size = max(DORIS_MIN_BATCH_SIZE, batch_size)
    offset = 0
    while offset < len(converted_rows):
        batch = converted_rows[offset : offset + current_batch_size]
        try:
            with conn.cursor() as cursor:
                cursor.executemany(insert_sql, batch)
            conn.commit()
            offset += len(batch)
            continue
        except Exception as exc:
            conn.rollback()
            if _is_retryable_insert_error(exc) and current_batch_size > DORIS_MIN_BATCH_SIZE:
                current_batch_size = max(DORIS_MIN_BATCH_SIZE, current_batch_size // 2)
                print(
                    f"[WARN] Doris batch insert hit resource pressure for {db_name}.{safe_table}; "
                    f"reducing batch size to {current_batch_size}"
                )
                try:
                    conn.close()
                except Exception:
                    pass
                time.sleep(2)
                conn = connect(database=db_name)
                continue

            print(f"[WARN] Falling back to row-by-row insert for {db_name}.{safe_table}")
            for row in batch:
                conn = _insert_single_row(conn, insert_sql, row, db_name, safe_table)
            offset += len(batch)
    return conn


def load_database(db_id: str, drop_first: bool = False):
    source_sqlite = sqlite_path(db_id)
    safe_db = clean_identifier(db_id)
    conn = connect()
    try:
        with conn.cursor() as cursor:
            if drop_first:
                cursor.execute(f"DROP DATABASE IF EXISTS `{safe_db}`")
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{safe_db}`")
        conn.commit()
    finally:
        conn.close()

    db_conn = connect(database=safe_db)
    name_map = {"db_id": db_id, "clean_db": safe_db, "tables": {}}
    try:
        for table_name in get_tables(source_sqlite):
            columns = get_columns(source_sqlite, table_name)
            if not columns:
                continue
            text_lengths = max_text_lengths(source_sqlite, table_name, columns)
            safe_table = clean_identifier(table_name)
            name_map["tables"][table_name] = {
                "clean_table": safe_table,
                "columns": {col["original_name"]: col["clean_name"] for col in columns},
            }
            with db_conn.cursor() as cursor:
                cursor.execute(f"DROP TABLE IF EXISTS `{safe_table}`")
                cursor.execute(build_create_table_sql(safe_db, table_name, columns, text_lengths))
            db_conn.commit()
            rows = fetch_all_rows(source_sqlite, table_name)
            db_conn = insert_rows(db_conn, safe_db, table_name, columns, rows)
    finally:
        db_conn.close()

    write_name_map(NAME_MAP_DIR / f"{db_id}.json", name_map)


def load_all(drop_first: bool = False, only_db: str | None = None):
    dbs = [only_db] if only_db else list_bird_databases()
    for db_id in dbs:
        print(f"[INFO] loading SQLite -> Doris for {db_id}")
        load_database(db_id, drop_first=drop_first)


def test_query():
    conn = connect()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchall()
        print("[INFO] Doris query check passed")
    finally:
        conn.close()


def status():
    docker_compose("ps")


def main():
    parser = argparse.ArgumentParser(description="Manage local Doris environment for UniQL")
    parser.add_argument("--action", choices=["up", "wait", "load", "test", "all", "down", "status"], default="all")
    parser.add_argument("--drop-first", action="store_true")
    parser.add_argument("--only-db", default=None)
    args = parser.parse_args()

    if args.action == "up":
        compose_up()
        return
    if args.action == "wait":
        wait_for_fe()
        ensure_backend()
        return
    if args.action == "load":
        load_all(drop_first=args.drop_first, only_db=args.only_db)
        return
    if args.action == "test":
        test_query()
        return
    if args.action == "down":
        compose_down()
        return
    if args.action == "status":
        status()
        return

    compose_up()
    wait_for_fe()
    ensure_backend()
    load_all(drop_first=args.drop_first, only_db=args.only_db)
    test_query()


if __name__ == "__main__":
    main()
