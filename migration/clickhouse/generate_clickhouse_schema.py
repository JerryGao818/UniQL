import json
import clickhouse_connect

CH_CONFIG = {
    "host": "localhost",
    "port": 8124,
    "username": "default",
    "password": "",
}

TARGET_DATABASES = [
    'california_schools', 'card_games', 'european_football_2', 
    'formula_1', 'student_club', 'thrombosis_prediction', 
    'toxicology', 'superhero', 'codebase_community', 
    'debit_card_specializing', 'financial'
]

CH_SCHEMA_JSON_FILE = './clickhouse_schema.json'

def get_ch_schema_info(db_name):
    """Migration helper."""
    try:
        ch_client = clickhouse_connect.get_client(database=db_name, **CH_CONFIG)
        
        res = ch_client.query(f"""
            SELECT table, name, type 
            FROM system.columns 
            WHERE database = '{db_name}' 
            ORDER BY table, position
        """)
        
        schema = ""
        current_table = None
        for table, name, dtype in res.result_rows:
            if table != current_table:
                schema += f"\nTable: `{table}`\n"
                current_table = table
            schema += f"  - `{name}` ({dtype})\n"
            
        return schema.strip()
    except Exception as e:
        return f"Schema error for {db_name}: {e}"

def export_ch_schemas_to_json():
    ch_schema_map = {}
    
    print(f"Connecting to ClickHouse to extract schemas...")
    
    for db_id in TARGET_DATABASES:
        print(f"  Extracting: {db_id}...", end="", flush=True)
        schema_text = get_ch_schema_info(db_id)
        ch_schema_map[db_id] = schema_text
        print(" Done.")

    with open(CH_SCHEMA_JSON_FILE, 'w', encoding='utf-8') as f:
        json.dump(ch_schema_map, f, indent=4, ensure_ascii=False)
    
    print(f"\n[Success] ClickHouse schemas saved to: {CH_SCHEMA_JSON_FILE}")

if __name__ == "__main__":
    export_ch_schemas_to_json()
