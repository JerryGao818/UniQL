import json
import duckdb
import os

DUCKDB_PATH = '/data1/databases/duck_db/bird_research.duckdb' 
SCHEMA_OUTPUT_FILE = './duckdb_schema.json'

TARGET_DATABASES = [
    'california_schools', 'card_games', 'european_football_2', 
    'formula_1', 'student_club', 'thrombosis_prediction', 
    'toxicology', 'superhero', 'codebase_community', 
    'debit_card_specializing', 'financial'
]

def get_duckdb_schema_info(db_id):
    """Migration helper."""
    schema_str = ""
    conn = None
    try:
        conn = duckdb.connect(DUCKDB_PATH, read_only=True)
        rows = conn.execute(f"""
            SELECT table_name, column_name, data_type 
            FROM information_schema.columns 
            WHERE table_schema = '{db_id}' 
            ORDER BY table_name, ordinal_position;
        """).fetchall()
        
        if not rows:
            return f"No schema info found for {db_id}"

        current_table = None
        for table_name, col_name, data_type in rows:
            if table_name != current_table:
                schema_str += f"\nTable: \"{table_name}\"\n"
                current_table = table_name
            schema_str += f"  - \"{col_name}\" ({data_type})\n"
            
    except Exception as e:
        schema_str = f"Error fetching schema for {db_id}: {e}"
    finally:
        if conn: conn.close()
    return schema_str.strip()

def export_all_schemas():
    schema_map = {}
    
    print(f"Starting schema extraction from {DUCKDB_PATH}...")
    
    for db_id in TARGET_DATABASES:
        print(f"  Processing: {db_id}...", end="", flush=True)
        info = get_duckdb_schema_info(db_id)
        schema_map[db_id] = info
        print(" Done.")

    with open(SCHEMA_OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(schema_map, f, indent=4, ensure_ascii=False)
    
    print(f"\nSuccessfully saved all schemas to: {SCHEMA_OUTPUT_FILE}")

if __name__ == "__main__":
    export_all_schemas()
