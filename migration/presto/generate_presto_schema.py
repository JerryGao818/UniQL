import os
import sqlite3
import json
import re

DB_ROOT_DIR = '/home/pkuccadm/huwenp/emb/EvoSD/bird/dev_databases'
OUTPUT_FILE = './data/presto_schema.json'

def clean_col_name(name):
    """Migration helper."""
    clean = re.sub(r'[^a-zA-Z0-9_]', '_', name).lower()
    clean = re.sub(r'_+', '_', clean)
    clean = clean.strip('_')
    if not clean: clean = "col_unknown"
    if clean[0].isdigit(): clean = "col_" + clean
    if clean in ['order', 'group', 'user', 'date', 'timestamp', 'interval', 'from', 'to', 'select', 'table']:
        clean = f"{clean}_col"
    return clean

def map_sqlite_to_presto_type(sqlite_type):
    st = sqlite_type.upper()
    if 'INT' in st: return 'INTEGER'
    if 'REAL' in st or 'FLOA' in st or 'DOUB' in st: return 'DOUBLE'
    if 'BOOL' in st: return 'BOOLEAN'
    if 'DATE' in st: return 'DATE'
    if 'TIME' in st: return 'TIMESTAMP'
    return 'VARCHAR'

def get_presto_schema(db_path):
    """Migration helper."""
    schema_str = ""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row[0] for row in cursor.fetchall()]
        
        for table in tables:
            if table.startswith('sqlite_'): continue
            
            presto_table = clean_col_name(table)
            schema_str += f"\nTable: `{presto_table}`\n"
            
            cursor.execute(f'PRAGMA table_info("{table}")')
            cols = cursor.fetchall()
            for col in cols:
                # col[1] name, col[2] type
                presto_col = clean_col_name(col[1])
                presto_type = map_sqlite_to_presto_type(col[2])
                schema_str += f"  - `{presto_col}` ({presto_type})\n"
                
        conn.close()
    except Exception as e:
        return f"Error reading schema: {e}"
        
    return schema_str.strip()

def main():
    if not os.path.exists(os.path.dirname(OUTPUT_FILE)):
        os.makedirs(os.path.dirname(OUTPUT_FILE))

    schema_data = {}
    db_ids = [d for d in os.listdir(DB_ROOT_DIR) if os.path.isdir(os.path.join(DB_ROOT_DIR, d))]
    
    print(f"Found {len(db_ids)} databases in {DB_ROOT_DIR}")
    
    for idx, db_id in enumerate(db_ids):
        db_path = os.path.join(DB_ROOT_DIR, db_id, f"{db_id}.sqlite")
        if not os.path.exists(db_path):
            print(f"  [{idx+1}/{len(db_ids)}] Skipping {db_id} (sqlite file not found)")
            continue
            
        print(f"  [{idx+1}/{len(db_ids)}] Processing {db_id}...")
        schema = get_presto_schema(db_path)
        if schema:
            schema_data[db_id] = schema
        else:
            print(f"  [{idx+1}/{len(db_ids)}] Skipping {db_id} (empty schema)")

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(schema_data, f, indent=2, ensure_ascii=False)
    
    print(f"\nSuccessfully saved Presto schemas to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
