import argparse
import json
import socket
import time
from pathlib import Path

import requests
import sys

REPO_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR))

from sqlite_dataset_utils import (  # noqa: E402
    clean_identifier,
    export_table_to_parquet,
    get_columns,
    get_tables,
    list_bird_databases,
    sqlite_path,
    write_name_map,
)

import subprocess


COMPOSE_FILE = PROJECT_DIR / "docker-compose.yml"
WAREHOUSE_DIR = PROJECT_DIR / "warehouse"
NAME_MAP_DIR = PROJECT_DIR / "results" / "name_map"
DRILL_STATE_URL = "http://127.0.0.1:8047/state"
DRILL_QUERY_URL = "http://127.0.0.1:8047/query.json"
DRILL_STORAGE_URL = "http://127.0.0.1:8047/storage/dfs.json"


def run(cmd, cwd=None, check=True, capture_output=False):
    return subprocess.run(cmd, cwd=cwd, check=check, capture_output=capture_output, text=True)


def docker_compose(*args, capture_output=False):
    return run(["docker", "compose", "-f", str(COMPOSE_FILE), *args], cwd=PROJECT_DIR, capture_output=capture_output)


def compose_up(force_recreate: bool = False):
    args = ["up", "-d"]
    if force_recreate:
        args.append("--force-recreate")
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
    return ((result.stdout or "") + (result.stderr or "")).strip()


def drill_http_ready() -> bool:
    try:
        response = requests.get(DRILL_STATE_URL, timeout=5)
        state_text = response.text.lower()
        if response.status_code == 200 and ("online" in state_text or "running" in state_text):
            return True
    except Exception:
        pass
    try:
        payload = {"queryType": "SQL", "query": "SELECT 1", "autoLimit": 1}
        response = requests.post(DRILL_QUERY_URL, json=payload, timeout=10)
        body = response.json()
        if response.status_code == 200 and body.get("queryState") == "COMPLETED":
            return True
    except Exception:
        pass
    return False


def wait_for_drill(timeout_sec=300):
    print("[INFO] waiting for Drill to become ready")
    deadline = time.time() + timeout_sec
    forced_restart = False
    while time.time() < deadline:
        status = container_status("uniql-drill")
        if status in {"missing", "exited"}:
            compose_up(force_recreate=True)
            time.sleep(5)
            status = container_status("uniql-drill")
        if status == "exited":
            logs = container_logs("uniql-drill")
            raise RuntimeError(f"Drill container exited unexpectedly.\n\n{logs}")
        try:
            with socket.create_connection(("127.0.0.1", 8047), timeout=5):
                pass
            if drill_http_ready():
                print("[INFO] Drill is ready")
                return
        except Exception:
            pass
        if not forced_restart and time.time() + 60 < deadline:
            print("[WARN] Drill looks stuck; recreating container once")
            compose_down()
            compose_up(force_recreate=True)
            forced_restart = True
            time.sleep(8)
            continue
        time.sleep(5)
    logs = container_logs("uniql-drill")
    raise TimeoutError(f"Drill did not become ready in time.\n\nRecent logs:\n{logs}")


def configure_workspace():
    print("[INFO] configuring Drill dfs.bird workspace")
    response = requests.get(DRILL_STORAGE_URL, timeout=30)
    response.raise_for_status()
    payload = response.json()
    config = payload.get("config", {})
    workspaces = config.get("workspaces") or {}
    workspaces["bird"] = {
        "location": "/mnt/bird_warehouse",
        "writable": False,
        "defaultInputFormat": "parquet",
    }
    config["enabled"] = True
    config["workspaces"] = workspaces
    post_body = {"name": "dfs", "config": config}
    post_response = requests.post(DRILL_STORAGE_URL, json=post_body, timeout=30)
    post_response.raise_for_status()


def load_database(db_id: str):
    source_sqlite = sqlite_path(db_id)
    safe_db = clean_identifier(db_id)
    target_db_dir = WAREHOUSE_DIR / safe_db
    target_db_dir.mkdir(parents=True, exist_ok=True)

    name_map = {"db_id": db_id, "clean_db": safe_db, "tables": {}}

    for table_name in get_tables(source_sqlite):
        columns = get_columns(source_sqlite, table_name)
        if not columns:
            continue
        safe_table = clean_identifier(table_name)
        name_map["tables"][table_name] = {
            "clean_table": safe_table,
            "columns": {col["original_name"]: col["clean_name"] for col in columns},
        }
        table_dir = target_db_dir / safe_table
        table_dir.mkdir(parents=True, exist_ok=True)
        output_file = table_dir / "data.parquet"
        export_table_to_parquet(source_sqlite, table_name, output_file, columns)

    write_name_map(NAME_MAP_DIR / f"{db_id}.json", name_map)


def load_all(only_db: str | None = None):
    dbs = [only_db] if only_db else list_bird_databases()
    for db_id in dbs:
        print(f"[INFO] loading SQLite -> Drill files for {db_id}")
        load_database(db_id)


def test_query():
    payload = {"queryType": "SQL", "query": "SELECT 1", "autoLimit": 1000}
    response = requests.post(DRILL_QUERY_URL, json=payload, timeout=30)
    response.raise_for_status()
    body = response.json()
    if body.get("queryState") != "COMPLETED":
        raise RuntimeError(body.get("errorMessage", body))
    print("[INFO] Drill query check passed")


def status():
    docker_compose("ps")


def main():
    parser = argparse.ArgumentParser(description="Manage local Drill environment for UniQL")
    parser.add_argument("--action", choices=["up", "wait", "load", "test", "all", "down", "status"], default="all")
    parser.add_argument("--only-db", default=None)
    args = parser.parse_args()

    if args.action == "up":
        compose_up()
        return
    if args.action == "wait":
        compose_up()
        wait_for_drill()
        configure_workspace()
        return
    if args.action == "load":
        load_all(only_db=args.only_db)
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
    wait_for_drill()
    configure_workspace()
    load_all(only_db=args.only_db)
    test_query()


if __name__ == "__main__":
    main()
