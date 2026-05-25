import argparse
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path

import requests

REPO_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = Path(__file__).resolve().parent
import sys

sys.path.insert(0, str(PROJECT_DIR))

from sqlite_dataset_utils import (  # noqa: E402
    clean_identifier,
    get_columns,
    get_tables,
    list_bird_databases,
    map_sqlite_to_hive_type,
    sqlite_path,
    write_name_map,
)


COMPOSE_FILE = PROJECT_DIR / "docker-compose.yml"
NAME_MAP_DIR = PROJECT_DIR / "results" / "name_map"
TRINO_URL = "http://127.0.0.1:8080/v1/info"
TRINO_QUERY_URL = "http://127.0.0.1:8080/v1/statement"
HDFS_ROOT_DIR = "/user/hive/warehouse"
HIVE_CLI = "/opt/hive/bin/hive"

CONTAINERS = {
    "namenode": "uniql-trino-namenode",
    "hive": "uniql-trino-hive-server",
    "metastore": "uniql-trino-hive-metastore",
    "postgres": "uniql-trino-hive-postgres",
    "trino": "uniql-trino",
}

METASTORE_DB = "metastore"
METASTORE_USER = "hive"


def run(cmd, cwd=None, check=True, capture_output=False):
    return subprocess.run(
        cmd,
        cwd=cwd,
        check=check,
        capture_output=capture_output,
        text=True,
    )


def docker_compose(*args, capture_output=False):
    return run(["docker", "compose", "-f", str(COMPOSE_FILE), *args], cwd=PROJECT_DIR, capture_output=capture_output)


def docker_compose_run(service, *command, capture_output=False, check=True):
    return run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "run", "-T", "--rm", "--no-deps", service, *command],
        cwd=PROJECT_DIR,
        capture_output=capture_output,
        check=check,
    )


def docker_exec(container, command, check=True, capture_output=False):
    return run(
        ["docker", "exec", "-i", container, "bash", "--noprofile", "--norc", "-lc", command],
        check=check,
        capture_output=capture_output,
    )


def docker_cp(src, dst):
    run(["docker", "cp", str(src), dst])


def compose_up(*services):
    args = ["up", "-d", *services] if services else ["up", "-d"]
    docker_compose(*args)


def compose_down():
    docker_compose("down")


def container_status(container: str) -> str:
    result = run(["docker", "inspect", "-f", "{{.State.Status}}", container], check=False, capture_output=True)
    if result.returncode != 0:
        return "missing"
    return result.stdout.strip() or "unknown"


def container_logs(container: str, tail: int = 120) -> str:
    result = run(["docker", "logs", "--tail", str(tail), container], check=False, capture_output=True)
    text = (result.stdout or "") + (result.stderr or "")
    return text.strip()


def ensure_container_not_exited(container: str, label: str):
    status = container_status(container)
    if status == "exited":
        logs = container_logs(container)
        raise RuntimeError(f"{label} exited unexpectedly.\n\n{logs}")


def wait_for_postgres(timeout_sec=180):
    print("[INFO] waiting for Hive metastore PostgreSQL to become ready")
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        result = docker_exec(
            CONTAINERS["postgres"],
            f"pg_isready -U {METASTORE_USER} -d {METASTORE_DB}",
            check=False,
            capture_output=True,
        )
        if result.returncode == 0:
            print("[INFO] Hive metastore PostgreSQL is ready")
            return
        ensure_container_not_exited(CONTAINERS["postgres"], "Hive metastore PostgreSQL")
        time.sleep(3)
    raise TimeoutError("Hive metastore PostgreSQL did not become ready in time")


def metastore_schema_exists() -> bool:
    query = (
        "psql -U {user} -d {db} -tAc "
        "\"SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = 'public' AND lower(table_name) = 'version' LIMIT 1;\""
    ).format(user=METASTORE_USER, db=METASTORE_DB)
    result = docker_exec(CONTAINERS["postgres"], query, check=False, capture_output=True)
    return result.returncode == 0 and result.stdout.strip() == "1"


def ensure_metastore_schema():
    print("[INFO] checking Hive metastore schema")
    if metastore_schema_exists():
        print("[INFO] Hive metastore schema already initialized")
        return

    print("[INFO] initializing Hive metastore schema")
    result = docker_compose_run(
        "hive-metastore",
        "/opt/hive/bin/schematool",
        "-dbType",
        "postgres",
        "-initSchema",
        capture_output=True,
        check=False,
    )
    output = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
    if result.returncode != 0:
        lowered = output.lower()
        if "already exists" not in lowered and "version information already exists" not in lowered:
            raise RuntimeError(f"Hive metastore schema initialization failed.\n\n{output}")

    if not metastore_schema_exists():
        raise RuntimeError("Hive metastore schema init command finished, but VERSION table is still missing.")

    print("[INFO] Hive metastore schema is ready")


def wait_for_tcp(host: str, port: int, label: str, timeout_sec=300):
    print(f"[INFO] waiting for {label} to become ready")
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=5):
                print(f"[INFO] {label} is ready")
                return
        except OSError:
            time.sleep(3)
    raise TimeoutError(f"{label} did not become ready in time")


def wait_for_metastore(timeout_sec=300):
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        ensure_container_not_exited(CONTAINERS["metastore"], "Hive metastore")
        try:
            with socket.create_connection(("127.0.0.1", 9083), timeout=5):
                print("[INFO] Hive metastore is ready")
                return
        except OSError:
            time.sleep(3)
    raise TimeoutError("Hive metastore did not become ready in time")


def wait_for_hive(timeout_sec=600):
    print("[INFO] waiting for Hive to become ready")
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        ensure_container_not_exited(CONTAINERS["hive"], "Hive server")
        result = docker_exec(CONTAINERS["hive"], f"{HIVE_CLI} -S -e 'SHOW DATABASES;'", check=False, capture_output=True)
        if result.returncode == 0:
            print("[INFO] Hive is ready")
            return
        time.sleep(5)
    raise TimeoutError("Hive did not become ready in time")


def wait_for_trino(timeout_sec=600):
    print("[INFO] waiting for Trino to become ready")
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        ensure_container_not_exited(CONTAINERS["trino"], "Trino")
        try:
            response = requests.get(TRINO_URL, timeout=5)
            if response.status_code == 200:
                print("[INFO] Trino is ready")
                return
        except Exception:
            pass
        time.sleep(5)
    raise TimeoutError("Trino did not become ready in time")


def run_hive_sql(sql: str):
    with tempfile.NamedTemporaryFile("w", suffix=".hql", encoding="utf-8", delete=False) as handle:
        handle.write(sql)
        local_path = Path(handle.name)
    remote_path = f"/tmp/{local_path.name}"
    try:
        docker_cp(local_path, f"{CONTAINERS['hive']}:{remote_path}")
        result = docker_exec(CONTAINERS["hive"], f"{HIVE_CLI} -S -f {remote_path}", check=False, capture_output=True)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Hive command failed")
    finally:
        try:
            docker_exec(CONTAINERS["hive"], f"rm -f {remote_path}", check=False)
        except Exception:
            pass
        local_path.unlink(missing_ok=True)


def hdfs_exec(command: str, check=True, capture_output=False):
    return docker_exec(CONTAINERS["namenode"], command, check=check, capture_output=capture_output)


def ensure_hdfs_dir(path: str):
    hdfs_exec(f"hdfs dfs -mkdir -p {path}")


def reset_hdfs_dir(path: str):
    hdfs_exec(f"hdfs dfs -rm -r -f {path}", check=False)
    hdfs_exec(f"hdfs dfs -mkdir -p {path}")


def upload_tsv(local_file: Path, hdfs_dir: str):
    remote_tmp = f"/tmp/{local_file.name}"
    docker_cp(local_file, f"{CONTAINERS['namenode']}:{remote_tmp}")
    try:
        hdfs_exec(f"hdfs dfs -put -f {remote_tmp} {hdfs_dir}/data.tsv")
    finally:
        hdfs_exec(f"rm -f {remote_tmp}", check=False)


def write_tsv(rows: list[tuple], output_file: Path):
    with open(output_file, "w", encoding="utf-8") as handle:
        for row in rows:
            cleaned = []
            for value in row:
                if value is None:
                    cleaned.append(r"\N")
                else:
                    text = str(value).replace("\\", "\\\\").replace("\t", " ").replace("\n", " ").replace("\r", "")
                    cleaned.append(text.strip())
            handle.write("\t".join(cleaned) + "\n")


def load_database(db_id: str, drop_first: bool = False):
    source_sqlite = sqlite_path(db_id)
    safe_db = clean_identifier(db_id)

    if drop_first:
        run_hive_sql(f"DROP DATABASE IF EXISTS {safe_db} CASCADE;")
    run_hive_sql(f"CREATE DATABASE IF NOT EXISTS {safe_db};")
    ensure_hdfs_dir(HDFS_ROOT_DIR)

    name_map = {"db_id": db_id, "clean_db": safe_db, "tables": {}}

    import sqlite3

    conn = sqlite3.connect(str(source_sqlite))
    try:
        cursor = conn.cursor()
        tables = get_tables(source_sqlite)
        for table_name in tables:
            columns = get_columns(source_sqlite, table_name)
            if not columns:
                continue

            safe_table = clean_identifier(table_name)
            name_map["tables"][table_name] = {
                "clean_table": safe_table,
                "columns": {col["original_name"]: col["clean_name"] for col in columns},
            }

            cursor.execute(f'SELECT * FROM "{table_name}"')
            rows = cursor.fetchall()

            hdfs_path = f"{HDFS_ROOT_DIR}/{safe_db}.db/{safe_table}"
            reset_hdfs_dir(hdfs_path)

            if rows:
                with tempfile.NamedTemporaryFile("w", suffix=".tsv", encoding="utf-8", delete=False) as handle:
                    temp_file = Path(handle.name)
                try:
                    write_tsv(rows, temp_file)
                    upload_tsv(temp_file, hdfs_path)
                finally:
                    temp_file.unlink(missing_ok=True)

            column_defs = ",\n                ".join(
                f"`{col['clean_name']}` {map_sqlite_to_hive_type(col['declared_type'])}" for col in columns
            )
            create_sql = f"""
            USE {safe_db};
            DROP TABLE IF EXISTS `{safe_table}`;
            CREATE EXTERNAL TABLE `{safe_table}` (
                {column_defs}
            )
            ROW FORMAT DELIMITED
            FIELDS TERMINATED BY '\\t'
            STORED AS TEXTFILE
            LOCATION '{hdfs_path}';
            """
            run_hive_sql(create_sql)

    finally:
        conn.close()

    write_name_map(NAME_MAP_DIR / f"{db_id}.json", name_map)


def load_all(drop_first: bool = False, only_db: str | None = None):
    dbs = [only_db] if only_db else list_bird_databases()
    for db_id in dbs:
        print(f"[INFO] loading SQLite -> Trino/Hive for {db_id}")
        load_database(db_id, drop_first=drop_first)


def test_query():
    headers = {
        "X-Trino-User": os.getenv("TRINO_USER", "trino"),
        "X-Trino-Catalog": os.getenv("TRINO_CATALOG", "hive"),
        "X-Trino-Schema": clean_identifier(list_bird_databases()[0]),
    }
    response = requests.post(TRINO_QUERY_URL, headers=headers, data="SELECT 1", timeout=30)
    response.raise_for_status()
    print("[INFO] Trino query check passed")


def status():
    docker_compose("ps")


def ensure_runtime_started():
    compose_up("namenode", "datanode", "hive-metastore-postgresql")
    wait_for_postgres()
    ensure_metastore_schema()
    compose_up("hive-metastore")
    wait_for_metastore()
    compose_up("hive-server", "trino")
    docker_compose("up", "-d", "--force-recreate", "trino")


def main():
    parser = argparse.ArgumentParser(description="Manage local Trino/Hive environment for UniQL")
    parser.add_argument("--action", choices=["up", "wait", "load", "test", "all", "down", "status"], default="all")
    parser.add_argument("--drop-first", action="store_true")
    parser.add_argument("--only-db", default=None)
    args = parser.parse_args()

    if args.action == "up":
        ensure_runtime_started()
        return
    if args.action == "wait":
        ensure_runtime_started()
        wait_for_hive()
        wait_for_trino()
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

    ensure_runtime_started()
    wait_for_hive()
    wait_for_trino()
    load_all(drop_first=args.drop_first, only_db=args.only_db)
    test_query()


if __name__ == "__main__":
    main()
