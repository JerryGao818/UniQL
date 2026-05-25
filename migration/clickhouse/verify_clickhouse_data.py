import sqlite3
import clickhouse_connect
import os

CH_CONFIG = {
    "host": "localhost",
    "port": 8124,
    "username": "default",
    "password": ""
}

BIRD_ROOT = os.getenv('UNIQL_BIRD_DB_ROOT', '<BIRD_DEV_DATABASES>')

DATABASES = [
    'superhero', 'codebase_community', 'debit_card_specializing', 
    'financial', 'california_schools', 'card_games', 
    'european_football_2', 'formula_1', 'student_club', 
    'thrombosis_prediction', 'toxicology'
]

# ===========================================

def get_ch_count(client, db_name, table_name):
    """Migration helper."""
    try:
        sql = f"SELECT count() FROM `{db_name}`.`{table_name}`"
        result = client.command(sql)
        return int(result)
    except Exception as e:
        err_msg = str(e)
        if "DB::Exception" in err_msg:
            return f"CH Err: {err_msg.split(':', 1)[-1].strip()[:30]}"
        return f"Error: {err_msg[:30]}"

def get_sqlite_row_counts(db_path):
    """Migration helper."""
    counts = {}
    if not os.path.exists(db_path):
        return None
        
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row[0] for row in cursor.fetchall() if not row[0].startswith('sqlite_')]
        
        for table in tables:
            try:
                cursor.execute(f'SELECT COUNT(*) FROM "{table}"')
                counts[table] = cursor.fetchone()[0]
            except Exception:
                counts[table] = -1
        
        conn.close()
        return counts
    except Exception:
        return None

def main():
    try:
        ch_client = clickhouse_connect.get_client(**CH_CONFIG)
    except Exception as e:
        print(f"[ERROR] {e}")
        return

    header = f"{'Database':<25} | {'Table':<35} | {'SQLite':<10} | {'ClickHouse':<10} | {'Status'}"
    print("=" * 115)
    print(header)
    print("=" * 115)

    total_tables = 0
    mismatch_count = 0
    
    for db_name in DATABASES:
        sqlite_file = os.path.join(BIRD_ROOT, db_name, f'{db_name}.sqlite')
        sqlite_counts = get_sqlite_row_counts(sqlite_file)
        
        if sqlite_counts is None:
            print(f"{db_name:<25} | [FILE NOT FOUND] SQLite file missing")
            print("-" * 115)
            continue

        for table, sqlite_cnt in sqlite_counts.items():
            total_tables += 1
            
            ch_cnt = get_ch_count(ch_client, db_name, table)
            
            status = ""
            if isinstance(ch_cnt, int):
                if sqlite_cnt == ch_cnt:
                    status = "OK"
                else:
                    status = "MISMATCH"
                    mismatch_count += 1
            else:
                status = "CH ERR"
                mismatch_count += 1
            
            ch_display = str(ch_cnt)
            print(f"{db_name:<25} | {table:<35} | {str(sqlite_cnt):<10} | {ch_display:<10} | {status}")

        print("-" * 115)

    print("[INFO] Operation status updated.")
    print(f"[INFO] Total tables checked: {total_tables}")
    if mismatch_count == 0:
        print("[INFO] Operation status updated.")
    else:
        print(f"[ERROR] Mismatched tables: {mismatch_count}")

if __name__ == "__main__":
    main()
