import sqlite3
import pymssql
import os
import datetime

MSSQL_HOST = 'localhost'
MSSQL_USER = 'SA'
MSSQL_PASS = 'Bird@123456'

BIRD_ROOT = '/home/pkuccadm/huwenp/emb/EvoSD/bird/dev_databases'
DATABASES = ['california_schools', 'card_games', 'european_football_2', 'formula_1', 'student_club', 'thrombosis_prediction', 'toxicology', 'superhero', 'codebase_community', 'debit_card_specializing', 'financial']
# ===========================================

def get_mssql_conn(db_name=None, autocommit=False):
    """Migration helper."""
    conn = pymssql.connect(
        server=MSSQL_HOST,
        user=MSSQL_USER,
        password=MSSQL_PASS,
        database=db_name if db_name else 'master',
        autocommit=autocommit,
        charset='utf8'
    )
    return conn

def sanitize_identifier(name):
    """
    Migration helper.
    """
    clean_name = name.replace('"', '').replace('`', '').replace('[', '').replace(']', '')
    return f"[{clean_name}]"

def map_sqlite_to_mssql_type(sqlite_type):
    """Migration helper."""
    st = sqlite_type.upper()
    if 'DATETIME' in st or 'TIMESTAMP' in st:
        return 'DATETIME2(3)'
    if st == 'DATE':
        return 'DATE'
    if 'INT' in st: return 'BIGINT'
    if 'REAL' in st or 'FLOA' in st or 'DOUB' in st: return 'FLOAT'
    if 'BOOL' in st: return 'BIT'
    if 'BLOB' in st: return 'VARBINARY(MAX)'
    if 'TIME' in st: return 'NVARCHAR(100)'
    return 'NVARCHAR(MAX)'

def clean_val_for_mssql(val):
    """Migration helper."""
    if val is None:
        return None
    
    if isinstance(val, bool):
        return 1 if val else 0
    
    if isinstance(val, bytes):
        return val
        
    if isinstance(val, str):
        if '\x00' in val: val = val.replace('\x00', '')
        return val
        
    return val

def main():
    only_dbs_raw = os.getenv("ONLY_DATABASES", "").strip()
    target_dbs = DATABASES
    if only_dbs_raw:
        wanted = {name.strip() for name in only_dbs_raw.split(",") if name.strip()}
        target_dbs = [db for db in DATABASES if db in wanted]
        print(f"[ERROR] {e}")

    try:
        master_conn = get_mssql_conn(autocommit=True)
        master_cursor = master_conn.cursor()
    except Exception as e:
        print(f"[ERROR] {e}")
        return

    for db_name in target_dbs:
        sqlite_file = os.path.join(BIRD_ROOT, db_name, f'{db_name}.sqlite')
        if not os.path.exists(sqlite_file):
            print(f"[INFO] Processing database: {db_name}")
            continue

        print(f"[INFO] Processing database: {db_name}")

        try:
            # master_cursor.execute(f"ALTER DATABASE [{db_name}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE")
            master_cursor.execute(f"IF DB_ID('{db_name}') IS NOT NULL DROP DATABASE [{db_name}]")
            master_cursor.execute(f"CREATE DATABASE [{db_name}]")
            print(f"[INFO] Processing database: {db_name}")
        except Exception as e:
            print(f"[ERROR] {e}")
            continue

        mssql_conn = get_mssql_conn(db_name=db_name, autocommit=False)
        mssql_cursor = mssql_conn.cursor()
        
        sqlite_conn = sqlite3.connect(sqlite_file)
        sqlite_cursor = sqlite_conn.cursor()

        sqlite_cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row[0] for row in sqlite_cursor.fetchall()]

        for table_name in tables:
            if table_name.startswith('sqlite_'): continue
            
            print(f"[INFO] Processing table: {table_name}")
            
            sqlite_cursor.execute(f'PRAGMA table_info("{table_name}")')
            cols_info = sqlite_cursor.fetchall()
            
            cols_def = []
            placeholders = []
            
            for col in cols_info:
                # col: (cid, name, type, notnull, dflt, pk)
                c_name = sanitize_identifier(col[1])
                c_type = map_sqlite_to_mssql_type(col[2])
                
                pk_def = " PRIMARY KEY" if col[5] == 1 else ""
                if pk_def and 'MAX' in c_type:
                    c_type = 'NVARCHAR(450)' # 900 bytes limit for index
                
                cols_def.append(f"{c_name} {c_type}")
                placeholders.append("%s")

            safe_table = sanitize_identifier(table_name)
            create_sql = f"CREATE TABLE {safe_table} ({', '.join(cols_def)})"
            
            try:
                mssql_cursor.execute(create_sql)
            except Exception as e:
                print(f"[ERROR] {e}")
                mssql_conn.rollback()
                continue

            sqlite_cursor.execute(f'SELECT * FROM "{table_name}"')
            rows = sqlite_cursor.fetchall()
            
            if rows:
                insert_sql = f"INSERT INTO {safe_table} VALUES ({','.join(placeholders)})"
                
                batch_data = []
                for row in rows:
                    batch_data.append(tuple(clean_val_for_mssql(v) for v in row))
                
                try:
                    batch_size = 1000
                    for i in range(0, len(batch_data), batch_size):
                        batch = batch_data[i:i+batch_size]
                        mssql_cursor.executemany(insert_sql, batch)
                    
                    mssql_conn.commit()
                except Exception as e:
                    print(f"[ERROR] {e}")
                    mssql_conn.rollback()

        sqlite_conn.close()
        mssql_conn.close()
        print(f"  [Success] {db_name}")

    master_conn.close()

if __name__ == "__main__":
    main()
