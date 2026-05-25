import sqlite3
import subprocess
import re
import os

DOCKER_PRESTO = "presto-coordinator"

BIRD_ROOT = os.getenv('UNIQL_BIRD_DB_ROOT', '<BIRD_DEV_DATABASES>')

DATABASES = ['california_schools']
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

def get_presto_count(db_name, table_name):
    """Migration helper."""
    hive_db = clean_col_name(db_name)
    hive_table = clean_col_name(table_name)
    
    sql = f"SELECT COUNT(*) FROM {hive_db}.{hive_table}"
    # Presto CLI command
    cmd = f'docker exec -i {DOCKER_PRESTO} /opt/presto-cli --server localhost:8080 --catalog hive --schema default --execute "{sql}" --output-format CSV'
    
    try:
        ret = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        
        if ret.returncode != 0:
            err_msg = ret.stderr.split('\n')[0] if ret.stderr else "Unknown Error"
            return f"Error: {err_msg}"
        
        output = ret.stdout.strip().replace('"', '')
        
        if output.isdigit():
            return int(output)
        
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
    header = f"{'Database':<25} | {'Table':<30} | {'SQLite':<10} | {'Presto':<10} | {'Status'}"
    print("=" * 95)
    print(header)
    print("=" * 95)

    total_tables = 0
    mismatch_count = 0
    
    for db_name in DATABASES:
        sqlite_file = os.path.join(BIRD_ROOT, db_name, f'{db_name}.sqlite')
        sqlite_counts = get_sqlite_row_counts(sqlite_file)
        
        if not sqlite_counts:
            print(f"{db_name:<25} | {'(Not Found)':<30} | {'-':<10} | {'-':<10} | Skip")
            continue
            
        for table, sq_count in sqlite_counts.items():
            total_tables += 1
            
            presto_count = get_presto_count(db_name, table)
            
            status = "OK"
            if isinstance(presto_count, int):
                if presto_count != sq_count:
                    status = "MISMATCH"
                    mismatch_count += 1
            else:
                status = "ERROR"
                mismatch_count += 1
                
            print(f"{db_name:<25} | {table:<30} | {sq_count:<10} | {presto_count:<10} | {status}")

    print("=" * 95)
    print(f"Total Tables: {total_tables}")
    print(f"Mismatches: {mismatch_count}")

if __name__ == "__main__":
    main()
