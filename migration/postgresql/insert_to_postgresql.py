import sqlite3
import psycopg2
from psycopg2 import sql
import os

PG_HOST = os.getenv("UNIQL_POSTGRES_HOST", "localhost")
PG_PORT = os.getenv("UNIQL_POSTGRES_PORT", "5432")
PG_USER = os.getenv("UNIQL_POSTGRES_USER", "postgres")
PG_PASS = os.getenv("UNIQL_POSTGRES_PASSWORD", "<POSTGRES_PASSWORD>")

BIRD_ROOT = os.getenv('UNIQL_BIRD_DB_ROOT', '<BIRD_DEV_DATABASES>')
DATABASES = ['california_schools', 'card_games', 'european_football_2', 'formula_1', 'student_club', 'thrombosis_prediction', 'toxicology', 'superhero', 'codebase_community', 'debit_card_specializing', 'financial']
# ===========================================

def get_pg_connection(dbname=None, autocommit=False):
    """Migration helper."""
    conn = psycopg2.connect(
        host=PG_HOST,
        port=PG_PORT,
        user=PG_USER,
        password=PG_PASS,
        dbname=dbname if dbname else "postgres"
    )
    if autocommit:
        conn.autocommit = True
    return conn

def map_sqlite_type_to_pg(sqlite_type):
    """Migration helper."""
    st = sqlite_type.upper()
    if 'INT' in st: return 'BIGINT'
    if 'REAL' in st or 'FLOA' in st or 'DOUB' in st: return 'DOUBLE PRECISION'
    if 'BOOL' in st: return 'BOOLEAN'
    if 'BLOB' in st: return 'BYTEA'
    if 'DATE' in st or 'TIME' in st: return 'TIMESTAMP'
    return 'TEXT'

def clean_data_for_pg(val):
    """Migration helper."""
    if val is None:
        return None
    
    if isinstance(val, str):
        if '\x00' in val:
            val = val.replace('\x00', '')
        return val
    
    if isinstance(val, int) and (val == 0 or val == 1):
        return val

    return val

def main():
    try:
        admin_conn = get_pg_connection(autocommit=True)
        admin_cursor = admin_conn.cursor()
    except Exception as e:
        print(f"[ERROR] {e}")
        return

    for db_name in DATABASES:
        sqlite_file = os.path.join(BIRD_ROOT, db_name, f'{db_name}.sqlite')
        if not os.path.exists(sqlite_file):
            print(f"[SKIP] File not found: {sqlite_file}")
            continue

        print(f"[INFO] Processing database: {db_name}")

        try:
            admin_cursor.execute(sql.SQL("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s"), [db_name])
            admin_cursor.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(db_name)))
            admin_cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(db_name)))
            print(f"[INFO] Processing database: {db_name}")
        except Exception as e:
            print(f"[ERROR] {e}")
            continue

        pg_conn = get_pg_connection(dbname=db_name)
        pg_cursor = pg_conn.cursor()

        sqlite_conn = sqlite3.connect(sqlite_file)
        sqlite_cursor = sqlite_conn.cursor()

        sqlite_cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row[0] for row in sqlite_cursor.fetchall()]

        for table_name in tables:
            if table_name.startswith('sqlite_'): continue

            print(f"[INFO] Processing table: {table_name}")

            sqlite_cursor.execute(f'PRAGMA table_info("{table_name}")')
            columns_info = sqlite_cursor.fetchall()
            
            cols_def = []
            col_names = []
            for col in columns_info:
                # col: (cid, name, type, notnull, dflt, pk)
                raw_name = col[1]
                raw_type = col[2]
                pg_type = map_sqlite_type_to_pg(raw_type)
                
                safe_col_name = f'"{raw_name.lower()}"'
                
                cols_def.append(f'{safe_col_name} {pg_type}')
                col_names.append(safe_col_name)
            
            safe_table_name = f'"{table_name.lower()}"'
            
            create_sql = f'CREATE TABLE {safe_table_name} ({", ".join(cols_def)})'
            
            try:
                pg_cursor.execute(create_sql)
            except Exception as e:
                print(f"[ERROR] {e}")
                pg_conn.rollback()
                continue

            sqlite_cursor.execute(f'SELECT * FROM "{table_name}"')
            rows = sqlite_cursor.fetchall()
            
            if rows:
                placeholders = ["%s"] * len(col_names)
                insert_sql = f'INSERT INTO {safe_table_name} VALUES ({", ".join(placeholders)})'
                
                batch_data = []
                for row in rows:
                    batch_data.append(tuple(clean_data_for_pg(val) for val in row))
                
                try:
                    pg_cursor.executemany(insert_sql, batch_data)
                    pg_conn.commit()
                except Exception as e:
                    print(f"[ERROR] {e}")
                    pg_conn.rollback()

        sqlite_conn.close()
        pg_conn.close()
        print(f"[INFO] Processing database: {db_name}")

    admin_conn.close()

if __name__ == "__main__":
    main()
