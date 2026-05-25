import sqlite3
import requests
import os
import json

DRUID_SQL_URL = "http://localhost:8888/druid/v2/sql"

BIRD_ROOT = os.getenv('UNIQL_BIRD_DB_ROOT', '<BIRD_DEV_DATABASES>')
DATABASES = ['california_schools', 'card_games', 'european_football_2', 'formula_1', 'student_club', 'thrombosis_prediction', 'toxicology', 'superhero', 'codebase_community', 'debit_card_specializing', 'financial']
# ===========================================

def get_druid_count(datasource):
    """Migration helper."""
    query = {
        "query": f'SELECT COUNT(*) as cnt FROM "{datasource}"'
    }
    try:
        response = requests.post(DRUID_SQL_URL, json=query, timeout=10)
        if response.status_code == 200:
            result = response.json()
            if result and len(result) > 0:
                return int(result[0]['cnt'])
            return 0
        elif response.status_code == 400:
            return "MISSING"
        else:
            return f"Error: {response.status_code}"
    except Exception as e:
        return f"Error: {e}"

def get_sqlite_row_counts(db_path):
    """Migration helper."""
    counts = {}
    if not os.path.exists(db_path): return None
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [row[0] for row in cursor.fetchall()]
    for table in tables:
        if table.startswith('sqlite_'): continue
        try:
            cursor.execute(f'SELECT COUNT(*) FROM "{table}"')
            counts[table] = cursor.fetchone()[0]
        except:
            counts[table] = -1
    conn.close()
    return counts

def main():
    header = f"{'Database':<25} | {'Table':<35} | {'SQLite':<10} | {'Druid':<10} | {'Status'}"
    print("=" * 105)
    print(header)
    print("=" * 105)

    total_tables = 0
    mismatch_count = 0
    missing_count = 0
    
    for db_name in DATABASES:
        sqlite_file = os.path.join(BIRD_ROOT, db_name, f'{db_name}.sqlite')
        sqlite_counts = get_sqlite_row_counts(sqlite_file)
        
        if sqlite_counts is None:
            print(f"{db_name:<25} | [FILE MISSING]")
            continue

        for table, sqlite_cnt in sqlite_counts.items():
            if sqlite_cnt == 0:
                continue
                
            total_tables += 1
            datasource_name = f"bird_{db_name}_{table}".lower()
            druid_cnt = get_druid_count(datasource_name)
            
            status = ""
            if isinstance(druid_cnt, int):
                if sqlite_cnt == druid_cnt:
                    status = "OK"
                else:
                    status = "MISMATCH"
                    mismatch_count += 1
            elif druid_cnt == "MISSING":
                status = "MISSING"
                missing_count += 1
            else:
                status = "DRUID ERR"
                mismatch_count += 1
            
            druid_display = str(druid_cnt)
            if len(druid_display) > 10: druid_display = "Error"
            
            print(f"{db_name:<25} | {table:<35} | {str(sqlite_cnt):<10} | {druid_display:<10} | {status}")
            
            if "Error" in str(druid_cnt):
                 print(f"{'':<25} |   -> {druid_cnt}")

        print("-" * 105)

    print(f"[INFO] Total tables checked: {total_tables}")
    if mismatch_count == 0 and missing_count == 0:
        print("[INFO] Operation status updated.")
    else:
        if mismatch_count > 0:
            print(f"[ERROR] Mismatched tables: {mismatch_count}")
        if missing_count > 0:
            print("[INFO] Operation status updated.")

if __name__ == "__main__":
    main()
