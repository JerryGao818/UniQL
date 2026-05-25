import sqlite3
import pymysql
import os

MYSQL_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "123456",
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.Cursor
}

BIRD_ROOT = './Bird_dataset/dev/dev_databases'

DATABASES = ['superhero', 'codebase_community', 'debit_card_specializing', 'financial', 'california_schools', 'card_games', 'european_football_2', 'formula_1', 'student_club', 'thrombosis_prediction', 'toxicology']
# ===========================================

def get_mysql_count(db_name, table_name):
    """Migration helper."""
    conn = None
    try:
        conn = pymysql.connect(database=db_name, **MYSQL_CONFIG)
        with conn.cursor() as cursor:
            sql = f"SELECT COUNT(*) FROM `{table_name}`"
            cursor.execute(sql)
            count = cursor.fetchone()[0]
            return count
    except pymysql.err.OperationalError as e:
        return f"Error: {e.args[1] if len(e.args)>1 else e}"
    except Exception as e:
        return f"Error: {str(e)}"
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
    header = f"{'Database':<25} | {'Table':<35} | {'SQLite':<10} | {'MySQL':<10} | {'Status'}"
    print("=" * 105)
    print(header)
    print("=" * 105)

    total_tables = 0
    mismatch_count = 0
    
    for db_name in DATABASES:
        sqlite_file = os.path.join(BIRD_ROOT, db_name, f'{db_name}.sqlite')
        sqlite_counts = get_sqlite_row_counts(sqlite_file)
        
        if sqlite_counts is None:
            print(f"{db_name:<25} | [FILE NOT FOUND] SQLite file missing")
            continue

        for table, sqlite_cnt in sqlite_counts.items():
            total_tables += 1
            
            mysql_cnt = get_mysql_count(db_name, table)
            
            status = ""
            if isinstance(mysql_cnt, int):
                if sqlite_cnt == mysql_cnt:
                    status = "OK"
                else:
                    status = "MISMATCH"
                    mismatch_count += 1
            else:
                status = "MYSQL ERR"
                mismatch_count += 1
            
            mysql_display = str(mysql_cnt)
            if len(mysql_display) > 10:
                mysql_display = "Error..."

            print(f"{db_name:<25} | {table:<35} | {str(sqlite_cnt):<10} | {mysql_display:<10} | {status}")
            
            if "Error" in str(mysql_cnt):
                 print(f"{'':<25} |   -> {mysql_cnt}")

        print("-" * 105)

    print("[INFO] Operation status updated.")
    print(f"[INFO] Total tables checked: {total_tables}")
    if mismatch_count == 0:
        print("[INFO] Operation status updated.")
    else:
        print(f"[ERROR] Mismatched tables: {mismatch_count}")

if __name__ == "__main__":
    main()
