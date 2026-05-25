import sqlite3
import subprocess
import re
import os

DOCKER_HIVE = "hive-server"

BIRD_ROOT = os.getenv('UNIQL_BIRD_DB_ROOT', '<BIRD_DEV_DATABASES>')

DATABASES = ['california_schools', 'card_games', 'european_football_2', 'formula_1', 'student_club', 'thrombosis_prediction', 'toxicology', 'superhero', 'codebase_community', 'debit_card_specializing', 'financial']
# ===========================================

def clean_col_name(name):
    """
    Migration helper.
    Migration helper.
    """
    clean = re.sub(r'[^a-zA-Z0-9_]', '_', name).lower()
    clean = re.sub(r'_+', '_', clean)
    clean = clean.strip('_')
    if not clean: clean = "col_unknown"
    if clean[0].isdigit():
        clean = "col_" + clean
    if clean in ['order', 'group', 'user', 'date', 'timestamp', 'interval', 'from', 'to', 'select', 'table']:
        clean = f"{clean}_col"
    return clean

def get_hive_count(db_name, table_name):
    """Migration helper."""
    hive_db = clean_col_name(db_name)
    hive_table = clean_col_name(table_name)
    
    sql = f"SELECT COUNT(*) FROM `{hive_db}`.`{hive_table}`;"
    cmd = f'docker exec -i {DOCKER_HIVE} hive -S -e "{sql}"'
    
    try:
        ret = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        
        if ret.returncode != 0:
            err_msg = ret.stderr.split('\n')[0] if ret.stderr else "Unknown Error"
            return f"Error: {err_msg}"
        
        output = ret.stdout.strip()
        
        lines = output.split('\n')
        for line in reversed(lines):
            if line.strip().isdigit():
                return int(line.strip())
        
        return f"Error: Can't parse '{output}'"
        
    except Exception as e:
        return f"Exception: {e}"

def get_sqlite_row_counts(db_path):
    """Migration helper."""
    counts = {}
    if not os.path.exists(db_path):
        return None
        
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
    header = f"{'Database':<25} | {'Table':<30} | {'SQLite':<10} | {'Hive':<10} | {'Status'}"
    print("=" * 95)
    print(header)
    print("=" * 95)

    total_tables = 0
    mismatch_count = 0
    
    for db_name in DATABASES:
        sqlite_file = os.path.join(BIRD_ROOT, db_name, f'{db_name}.sqlite')
        sqlite_counts = get_sqlite_row_counts(sqlite_file)
        
        if sqlite_counts is None:
            print(f"{db_name:<25} | [FILE MISSING]")
            continue

        for table, sqlite_cnt in sqlite_counts.items():
            total_tables += 1
            
            hive_cnt = get_hive_count(db_name, table)
            
            status = ""
            if isinstance(hive_cnt, int):
                if sqlite_cnt == hive_cnt:
                    status = "OK"
                else:
                    status = "MISMATCH"
                    mismatch_count += 1
            else:
                status = "HIVE ERR"
                mismatch_count += 1
            
            hive_display = str(hive_cnt)
            if len(hive_display) > 10: hive_display = "Error..."
            
            print(f"{db_name:<25} | {table:<30} | {str(sqlite_cnt):<10} | {hive_display:<10} | {status}")
            
            if "Error" in str(hive_cnt) or "Exception" in str(hive_cnt):
                 print(f"{'':<25} |   -> {hive_cnt}")

        print("-" * 95)

    print(f"[INFO] Total tables checked: {total_tables}")
    if mismatch_count == 0:
        print("[INFO] Operation status updated.")
    else:
        print(f"[ERROR] Mismatched tables: {mismatch_count}")

if __name__ == "__main__":
    main()
