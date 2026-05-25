import sqlite3
import oracledb
import os
from datetime import datetime

ADMIN_USER = "SYSTEM"
ADMIN_PASS = "123456"
ORACLE_DSN = "localhost:1521/XE" 
DEFAULT_USER_PASS = "Bird123456"

# DATABASES = ['superhero', 'codebase_community', 'debit_card_specializing', 'financial']
DATABASES = ['california_schools', 'card_games', 'european_football_2', 'formula_1', 'student_club', 'thrombosis_prediction', 'toxicology']
BIRD_ROOT = os.getenv('UNIQL_BIRD_DB_ROOT', '<BIRD_DEV_DATABASES>')
# ===========================================

def get_admin_connection():
    return oracledb.connect(user=ADMIN_USER, password=ADMIN_PASS, dsn=ORACLE_DSN)

def get_user_connection(username):
    return oracledb.connect(user=username, password=DEFAULT_USER_PASS, dsn=ORACLE_DSN)

def setup_oracle_user(admin_conn, username):
    cursor = admin_conn.cursor()
    try:
        cursor.execute('ALTER SESSION SET "_ORACLE_SCRIPT"=true')
        try:
            cursor.execute(f'DROP USER {username} CASCADE')
            print(f"[ERROR] {e}")
        except oracledb.DatabaseError:
            pass
        cursor.execute(f'CREATE USER {username} IDENTIFIED BY "{DEFAULT_USER_PASS}"')
        cursor.execute(f'GRANT CONNECT, RESOURCE, DBA TO {username}')
        cursor.execute(f'GRANT UNLIMITED TABLESPACE TO {username}')
    except Exception as e:
        print(f"  [Admin Error] {e}")
    finally:
        cursor.close()

def sanitize_identifier(name):
    return f'"{name.upper()}"'

def detect_column_max_length(sqlite_cursor, table_name, col_name):
    """
    Migration helper.
    """
    try:
        query = f'SELECT MAX(LENGTH("{col_name}")) FROM "{table_name}"'
        sqlite_cursor.execute(query)
        result = sqlite_cursor.fetchone()
        if result and result[0] is not None:
            return int(result[0])
        return 0
    except:
        return 0

def clean_val_for_oracle(val):
    """Migration helper."""
    if val is None: return None
    if isinstance(val, bool): return 1 if val else 0
    if isinstance(val, str):
        val = val.strip()
        if len(val) >= 10 and val[0].isdigit() and ('-' in val or ':' in val):
            try:
                val_clean = val.replace('T', ' ')
                if '.' in val_clean: val_clean = val_clean.split('.')[0]
                if len(val_clean) == 19: return datetime.strptime(val_clean, '%Y-%m-%d %H:%M:%S')
                if len(val_clean) == 10: return datetime.strptime(val_clean, '%Y-%m-%d')
            except:
                pass
    return val

def main():
    try:
        admin_conn = get_admin_connection()
    except Exception as e:
        print(f"[ERROR] {e}")
        return

    for db_name in DATABASES:
        sqlite_file = os.path.join(BIRD_ROOT, db_name, f'{db_name}.sqlite')
        if not os.path.exists(sqlite_file): continue

        print(f"[INFO] Processing database: {db_name}")
        oracle_username = db_name.upper()
        setup_oracle_user(admin_conn, oracle_username)

        try:
            user_conn = get_user_connection(oracle_username)
            user_cursor = user_conn.cursor()
            user_cursor.execute("ALTER SESSION SET NLS_DATE_FORMAT = 'YYYY-MM-DD HH24:MI:SS'")
        except Exception as e:
            print(f"  Login Failed: {e}")
            continue

        sqlite_conn = sqlite3.connect(sqlite_file)
        sqlite_cursor = sqlite_conn.cursor()
        
        sqlite_cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row[0] for row in sqlite_cursor.fetchall()]

        for table_name in tables:
            print(f"[INFO] Processing table: {table_name}")
            
            sqlite_cursor.execute(f"PRAGMA table_info('{table_name}')")
            cols_info = sqlite_cursor.fetchall()
            
            cols_def = []
            placeholders = []
            
            for col in cols_info:
                # col: (cid, name, type, notnull, dflt, pk)
                raw_name = col[1]
                raw_type = col[2].upper()
                
                c_name = sanitize_identifier(raw_name)
                c_type = 'VARCHAR2(4000)'

                if 'INT' in raw_type: c_type = 'NUMBER'
                elif 'REAL' in raw_type or 'FLOA' in raw_type or 'DOUB' in raw_type: c_type = 'NUMBER'
                elif 'DATE' in raw_type or 'TIME' in raw_type: c_type = 'DATE'
                elif 'BLOB' in raw_type: c_type = 'BLOB'
                else:
                    max_len = detect_column_max_length(sqlite_cursor, table_name, raw_name)
                    
                    if max_len > 4000:
                        print(f"[ERROR] {e}")
                        c_type = 'CLOB'
                    else:
                        c_type = 'VARCHAR2(4000)'
                
                cols_def.append(f"{c_name} {c_type}")
                placeholders.append(f":{len(placeholders)+1}")

            safe_table_name = sanitize_identifier(table_name)
            create_sql = f"CREATE TABLE {safe_table_name} ({', '.join(cols_def)})"
            
            try:
                user_cursor.execute(create_sql)
            except oracledb.DatabaseError as e:
                print(f"[ERROR] {e}")
                continue

            sqlite_cursor.execute(f'SELECT * FROM "{table_name}"')
            rows = sqlite_cursor.fetchall()
            if rows:
                insert_sql = f"INSERT INTO {safe_table_name} VALUES ({','.join(placeholders)})"
                batch_data = [ [clean_val_for_oracle(x) for x in r] for r in rows ]
                try:
                    user_cursor.executemany(insert_sql, batch_data)
                    user_conn.commit()
                except Exception as e:
                    print(f"[ERROR] {e}")

        sqlite_conn.close()
        user_cursor.close()
        user_conn.close()

    admin_conn.close()
    print("[INFO] Operation status updated.")

if __name__ == "__main__":
    main()
