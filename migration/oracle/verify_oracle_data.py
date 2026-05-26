import sqlite3
import oracledb
import os

ORACLE_DSN = os.getenv("UNIQL_ORACLE_DSN", "localhost:1521/XE")
DEFAULT_USER_PASS = os.getenv("UNIQL_ORACLE_USER_PASSWORD", "<ORACLE_PASSWORD>")

BIRD_ROOT = os.getenv('UNIQL_BIRD_DB_ROOT', '<BIRD_DEV_DATABASES>')
DATABASES = ['superhero', 'codebase_community', 'debit_card_specializing', 'financial', 'california_schools', 'card_games', 'european_football_2', 'formula_1', 'student_club', 'thrombosis_prediction', 'toxicology']
# ===========================================

def get_oracle_count(username, table_name):
    """Migration helper."""
    conn = None
    try:
        conn = oracledb.connect(user=username, password=DEFAULT_USER_PASS, dsn=ORACLE_DSN)
        cursor = conn.cursor()
        table_name = table_name.upper()
        cursor.execute(f'SELECT COUNT(*) FROM "{table_name}"')
        count = cursor.fetchone()[0]
        return count
    except Exception as e:
        return f"Error: {e}"
    finally:
        if conn: conn.close()

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
        if table.startswith('sqlite_'):
            continue
            
        try:
            cursor.execute(f'SELECT COUNT(*) FROM "{table}"')
            counts[table] = cursor.fetchone()[0]
        except Exception as e:
            counts[table] = -1
            
    conn.close()
    return counts

def main():
    header = f"{'Database':<25} | {'Table':<35} | {'SQLite':<10} | {'Oracle':<10} | {'Status'}"
    print("=" * 100)
    print(header)
    print("=" * 100)

    total_tables = 0
    mismatch_count = 0
    
    for db_name in DATABASES:
        sqlite_file = os.path.join(BIRD_ROOT, db_name, f'{db_name}.sqlite')
        sqlite_counts = get_sqlite_row_counts(sqlite_file)
        
        if sqlite_counts is None:
            print(f"{db_name:<25} | [FILE NOT FOUND] SQLite file missing")
            continue

        oracle_user = db_name.upper()

        for table, sqlite_cnt in sqlite_counts.items():
            total_tables += 1
            
            oracle_cnt = get_oracle_count(oracle_user, table)
            
            status = ""
            if isinstance(oracle_cnt, int):
                if sqlite_cnt == oracle_cnt:
                    status = "OK"
                else:
                    status = "MISMATCH"
                    mismatch_count += 1
            else:
                status = "ORACLE ERR"
                mismatch_count += 1
            
            print(f"{db_name:<25} | {table:<35} | {str(sqlite_cnt):<10} | {str(oracle_cnt):<10} | {status}")

        print("-" * 100)

    print("[INFO] Operation status updated.")
    print(f"[INFO] Total tables checked: {total_tables}")
    if mismatch_count == 0:
        print("[INFO] Operation status updated.")
    else:
        print(f"[ERROR] Mismatched tables: {mismatch_count}")

if __name__ == "__main__":
    main()
