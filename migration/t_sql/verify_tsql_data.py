import sqlite3
import pymssql
import os
import json

MSSQL_CONFIG = {
    'server': os.getenv("UNIQL_MSSQL_HOST", "localhost"),
    'user': os.getenv("UNIQL_MSSQL_USER", "SA"),
    'password': os.getenv("UNIQL_MSSQL_PASSWORD", "<MSSQL_PASSWORD>"),
    'charset': 'utf8'
}

BIRD_ROOT = os.getenv('UNIQL_BIRD_DB_ROOT', '<BIRD_DEV_DATABASES>')
DATABASES = ['california_schools', 'card_games', 'european_football_2', 'formula_1', 'student_club', 'thrombosis_prediction', 'toxicology', 'superhero', 'codebase_community', 'debit_card_specializing', 'financial']
SCHEMA_OUTPUT_FILE = 'mssql_schema.json'
# ===========================================

def sanitize_identifier(name):
    clean_name = name.replace('"', '').replace('`', '').replace('[', '').replace(']', '')
    return f"[{clean_name}]"

def get_mssql_count(db_name, table_name):
    conn = None
    try:
        conn = pymssql.connect(database=db_name, **MSSQL_CONFIG)
        cursor = conn.cursor()
        safe_table = sanitize_identifier(table_name)
        cursor.execute(f"SELECT COUNT(*) FROM {safe_table}")
        return cursor.fetchone()[0]
    except Exception as e:
        return f"Error: {e}"
    finally:
        if conn: conn.close()

def get_mssql_schema_str(db_name):
    """Migration helper."""
    conn = None
    schema_parts = []
    try:
        conn = pymssql.connect(database=db_name, **MSSQL_CONFIG)
        cursor = conn.cursor()
        
        sql = """
        SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE 
        FROM INFORMATION_SCHEMA.COLUMNS 
        WHERE TABLE_SCHEMA = 'dbo'
        ORDER BY TABLE_NAME, ORDINAL_POSITION
        """
        cursor.execute(sql)
        rows = cursor.fetchall()
        
        current_table = None
        table_buffer = []
        
        for t_name, c_name, d_type in rows:
            if t_name != current_table:
                if current_table:
                    schema_parts.append(f"Table: `{current_table}`")
                    schema_parts.extend(table_buffer)
                    schema_parts.append("")
                current_table = t_name
                table_buffer = []
            
            simple_type = d_type.upper()
            if 'INT' in simple_type: simple_type = 'INT'
            elif 'CHAR' in simple_type or 'TEXT' in simple_type: simple_type = 'STRING'
            elif 'FLOAT' in simple_type or 'REAL' in simple_type: simple_type = 'DOUBLE'
            elif 'BIT' in simple_type: simple_type = 'INT' # MSSQL boolean is BIT
            
            table_buffer.append(f"  - `{c_name}` ({simple_type})")
            
        if current_table:
            schema_parts.append(f"Table: `{current_table}`")
            schema_parts.extend(table_buffer)
            
    except Exception as e:
        return f"Error extracting schema: {e}"
    finally:
        if conn: conn.close()
        
    return "\n".join(schema_parts).strip()

def get_sqlite_row_counts(db_path):
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
        except: counts[table] = -1
    conn.close()
    return counts

def main():
    print(f"{'Database':<25} | {'Table':<35} | {'SQLite':<10} | {'MSSQL':<10} | {'Status'}")
    print("-" * 100)

    all_schemas = {}
    mismatch_count = 0

    for db_name in DATABASES:
        sqlite_file = os.path.join(BIRD_ROOT, db_name, f'{db_name}.sqlite')
        sqlite_counts = get_sqlite_row_counts(sqlite_file)
        
        if not sqlite_counts:
            print(f"{db_name:<25} | [FILE MISSING]")
            continue

        for table, sqlite_cnt in sqlite_counts.items():
            mssql_cnt = get_mssql_count(db_name, table)
            
            status = ""
            if isinstance(mssql_cnt, int):
                if sqlite_cnt == mssql_cnt:
                    status = "OK"
                else: 
                    status = "DIFF"
                    mismatch_count += 1
            else:
                status = "ERR"
                mismatch_count += 1
            
            disp_mssql = str(mssql_cnt)[:10]
            print(f"{db_name:<25} | {table:<35} | {str(sqlite_cnt):<10} | {disp_mssql:<10} | {status}")

        print("-" * 100)
        
        print(f"[INFO] Processing database: {db_name}")
        all_schemas[db_name] = get_mssql_schema_str(db_name)

    with open(SCHEMA_OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(all_schemas, f, indent=4, ensure_ascii=False)
    
    print(f"[ERROR] Mismatched tables: {mismatch_count}")
    print("[INFO] Operation status updated.")

if __name__ == "__main__":
    main()
