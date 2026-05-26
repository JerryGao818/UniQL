import sqlite3
import requests
import json
import os
import time

DRUID_OVERLORD_URL = "http://localhost:8081/druid/indexer/v1/task"
DRUID_COORDINATOR_URL = "http://localhost:8081/druid/indexer/v1/task/{task_id}/status"

BIRD_ROOT = os.getenv('UNIQL_BIRD_DB_ROOT', '<BIRD_DEV_DATABASES>')
DATABASES = ['california_schools', 'card_games', 'european_football_2', 'formula_1', 'student_club', 'thrombosis_prediction', 'toxicology', 'superhero', 'codebase_community', 'debit_card_specializing', 'financial']

HOST_TEMP_DIR = "/root/ai4db/NL2QL/druid/temp_data"
CONTAINER_TEMP_DIR = "/opt/data/temp_data"

# ===========================================

os.makedirs(HOST_TEMP_DIR, exist_ok=True)

def map_sqlite_type_to_druid(sqlite_type):
    """Migration helper."""
    st = sqlite_type.upper()
    if 'INT' in st: return 'long'
    if 'REAL' in st or 'FLOA' in st or 'DOUB' in st: return 'double'
    return 'string'

def wait_for_task(task_id):
    """Migration helper."""
    print("[INFO] Operation status updated.")
    while True:
        try:
            url = DRUID_COORDINATOR_URL.format(task_id=task_id)
            resp = requests.get(url)
            status_info = resp.json().get('status', {})
            status = status_info.get('status')
            if status == 'SUCCESS':
                print("[INFO] Operation status updated.")
                return True
            elif status == 'FAILED':
                print("[INFO] Operation status updated.")
                return False
            time.sleep(2)
        except Exception as e:
            print(f"[ERROR] {e}")
            return False

def ingest_to_druid(datasource, columns_info, rows):
    """Migration helper."""
    
    dimensions = []
    col_names = [col[1].lower() for col in columns_info]
    for col in columns_info:
        col_name = col[1].lower()
        col_type = map_sqlite_type_to_druid(col[2])
        dimensions.append({"name": col_name, "type": col_type})

    temp_filename = f"{datasource}.json"
    host_file_path = os.path.join(HOST_TEMP_DIR, temp_filename)
    
    default_timestamp = "2024-01-01T00:00:00Z"
    with open(host_file_path, 'w') as f:
        for row in rows:
            record = {"__time": default_timestamp}
            for i, val in enumerate(row):
                record[col_names[i]] = val
            f.write(json.dumps(record) + '\n')

    spec = {
        "type": "index_parallel",
        "spec": {
            "dataSchema": {
                "dataSource": datasource,
                "dimensionsSpec": {
                    "dimensions": dimensions
                },
                "timestampSpec": {
                    "column": "__time",
                    "format": "iso"
                },
                "granularitySpec": {
                    "type": "uniform",
                    "segmentGranularity": "ALL",
                    "queryGranularity": "NONE",
                    "rollup": False
                }
            },
            "ioConfig": {
                "type": "index_parallel",
                "inputSource": {
                    "type": "local",
                    "baseDir": CONTAINER_TEMP_DIR,
                    "filter": temp_filename
                },
                "inputFormat": {
                    "type": "json"
                },
                "appendToExisting": False
            },
            "tuningConfig": {
                "type": "index_parallel",
                "maxRowsInMemory": 100000,
                "forceGuaranteedRollup": True
            }
        }
    }

    try:
        response = requests.post(DRUID_OVERLORD_URL, json=spec)
        if response.status_code == 200:
            task_id = response.json().get('task')
            success = wait_for_task(task_id)
            if os.path.exists(host_file_path):
                os.remove(host_file_path)
            return success
        else:
            print("[INFO] Operation status updated.")
            return False
    except Exception as e:
        print(f"[ERROR] {e}")
        return False

def main():
    for db_name in DATABASES:
        sqlite_file = os.path.join(BIRD_ROOT, db_name, f'{db_name}.sqlite')
        if not os.path.exists(sqlite_file):
            print(f"[SKIP] File not found: {sqlite_file}")
            continue

        print(f"[INFO] Processing database: {db_name}")

        sqlite_conn = sqlite3.connect(sqlite_file)
        sqlite_cursor = sqlite_conn.cursor()

        sqlite_cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row[0] for row in sqlite_cursor.fetchall()]

        for table_name in tables:
            if table_name.startswith('sqlite_'): continue

            datasource_name = f"bird_{db_name}_{table_name}".lower()
            print(f"[INFO] Processing table: {table_name}")

            sqlite_cursor.execute(f'PRAGMA table_info("{table_name}")')
            columns_info = sqlite_cursor.fetchall()

            sqlite_cursor.execute(f'SELECT * FROM "{table_name}"')
            rows = sqlite_cursor.fetchall()

            if not rows:
                print(f"[INFO] Processing table: {table_name}")
                continue

            success = ingest_to_druid(datasource_name, columns_info, rows)
            if success:
                print(f"[INFO] Processing table: {table_name}")
            else:
                print(f"[INFO] Processing table: {table_name}")

        sqlite_conn.close()
        print(f"[INFO] Processing database: {db_name}")

if __name__ == "__main__":
    main()
