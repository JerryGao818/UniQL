import sqlite3
import duckdb
import os

DUCKDB_FILE = "/data1/databases/duck_db/bird_research.duckdb"

BIRD_ROOT = os.getenv('UNIQL_BIRD_DB_ROOT', '<BIRD_DEV_DATABASES>')

DATABASES = [
    'superhero', 'codebase_community', 'debit_card_specializing', 
    'financial', 'card_games', 'formula_1', 'student_club', 
    'thrombosis_prediction', 'toxicology'
]
# ===========================================

def get_duckdb_count(con, schema_name, table_name):
    """Migration helper."""
    try:
        sql = f'SELECT COUNT(*) FROM "{schema_name}"."{table_name}"'
        res = con.execute(sql).fetchone()
        return res[0]
    except Exception as e:
        err_msg = str(e).replace('\n', ' ')
        return f"Error: {err_msg[:40]}"

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
    if not os.path.exists(DUCKDB_FILE):
        print("[INFO] Operation status updated.")
        return

    con = duckdb.connect(DUCKDB_FILE, read_only=True)

    header = f"{'Database':<25} | {'Table':<35} | {'SQLite':<10} | {'DuckDB':<10} | {'Status'}"
    print("=" * 110)
    print(header)
    print("=" * 110)

    total_tables = 0
    mismatch_count = 0
    
    for db_name in DATABASES:
        sqlite_file = os.path.join(BIRD_ROOT, db_name, f'{db_name}.sqlite')
        sqlite_counts = get_sqlite_row_counts(sqlite_file)
        
        if sqlite_counts is None:
            print(f"{db_name:<25} | [FILE NOT FOUND] SQLite file missing at {sqlite_file}")
            continue

        for table, sqlite_cnt in sqlite_counts.items():
            total_tables += 1
            
            duck_cnt = get_duckdb_count(con, db_name, table)
            
            status = ""
            if isinstance(duck_cnt, int):
                if sqlite_cnt == duck_cnt:
                    status = "OK"
                else:
                    status = "MISMATCH"
                    mismatch_count += 1
            else:
                status = "DUCK ERR"
                mismatch_count += 1
            
            duck_display = str(duck_cnt)
            if len(duck_display) > 10: duck_display = "Error..."

            print(f"{db_name:<25} | {table:<35} | {str(sqlite_cnt):<10} | {duck_display:<10} | {status}")
            
            if "Error" in str(duck_cnt):
                 print(f"{'':<25} |   -> {duck_cnt}")

        print("-" * 110)

    con.close()

    print("[INFO] Operation status updated.")
    print(f"[INFO] Total tables checked: {total_tables}")
    if mismatch_count == 0:
        print("[INFO] Operation status updated.")
    else:
        print(f"[ERROR] Mismatched tables: {mismatch_count}")

if __name__ == "__main__":
    main()
