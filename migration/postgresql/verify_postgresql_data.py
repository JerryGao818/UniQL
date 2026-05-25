import sqlite3
import psycopg2
import os

PG_CONFIG = {
    "host": "localhost",
    "port": "5432",
    "user": "postgres",
    "password": "123456"
}

BIRD_ROOT = './Bird_dataset/dev/dev_databases'
DATABASES = ['california_schools', 'card_games', 'european_football_2', 'formula_1', 'student_club', 'thrombosis_prediction', 'toxicology', 'superhero', 'codebase_community', 'debit_card_specializing', 'financial']
# ===========================================

def get_pg_count(db_name, table_name):
    """Migration helper."""
    conn = None
    try:
        conn = psycopg2.connect(dbname=db_name, **PG_CONFIG)
        cursor = conn.cursor()
        
        cursor.execute(f'SELECT COUNT(*) FROM "{table_name.lower()}"')
        
        count = cursor.fetchone()[0]
        return count
    except Exception as e:
        return f"Error: {e}"
    finally:
        if conn: conn.close()

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
    header = f"{'Database':<25} | {'Table':<35} | {'SQLite':<10} | {'Postgres':<10} | {'Status'}"
    print("=" * 105)
    print(header)
    print("=" * 105)

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
            pg_cnt = get_pg_count(db_name, table)
            
            status = ""
            if isinstance(pg_cnt, int):
                if sqlite_cnt == pg_cnt:
                    status = "OK"
                else:
                    status = "MISMATCH"
                    mismatch_count += 1
            else:
                status = "PG ERR"
                mismatch_count += 1
            
            pg_display = str(pg_cnt)
            if len(pg_display) > 10: pg_display = "Error"
            
            print(f"{db_name:<25} | {table:<35} | {str(sqlite_cnt):<10} | {pg_display:<10} | {status}")
            
            if "Error" in str(pg_cnt):
                 print(f"{'':<25} |   -> {pg_cnt}")

        print("-" * 105)

    print(f"[INFO] Total tables checked: {total_tables}")
    if mismatch_count == 0:
        print("[INFO] Operation status updated.")
    else:
        print(f"[ERROR] Mismatched tables: {mismatch_count}")

if __name__ == "__main__":
    main()
