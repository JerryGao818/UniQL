import os
import sqlite3
import pandas as pd
import duckdb
from sqlalchemy import create_engine, MetaData, types

ROOT_DIR = os.getenv('UNIQL_BIRD_DB_ROOT', '<BIRD_DEV_DATABASES>')
DUCKDB_FILE = "/data1/databases/duck_db/bird_research.duckdb"

def map_sqlalchemy_type_to_duckdb(sqla_column):
    t = sqla_column.type
    if isinstance(t, types.BigInteger): return "BIGINT"
    if isinstance(t, types.Integer): return "INTEGER"
    if isinstance(t, types.SmallInteger): return "INTEGER"
    if isinstance(t, (types.Float, types.Numeric, types.REAL)): return "DOUBLE"
    return "VARCHAR"

def transfer_database(con, folder_name, sqlite_path):
    print(f"[INFO] Processing database: {folder_name}")
    
    con.execute(f"CREATE SCHEMA IF NOT EXISTS \"{folder_name}\"")
    
    sqlite_engine = create_engine(f"sqlite:///{sqlite_path}")
    metadata = MetaData()
    metadata.reflect(bind=sqlite_engine)
    
    for table in metadata.sorted_tables:
        table_name = table.name
        print(f"[INFO] Processing table: {table_name}")
        
        columns_gen = []
        for col in table.columns:
            db_type = map_sqlalchemy_type_to_duckdb(col)
            columns_gen.append(f"\"{col.name}\" {db_type}")
        
        col_str = ", ".join(columns_gen)
        full_table_name = f"\"{folder_name}\".\"{table_name}\""
        
        try:
            con.execute(f"DROP TABLE IF EXISTS {full_table_name}")
            con.execute(f"CREATE TABLE {full_table_name} ({col_str})")
            
            with sqlite3.connect(sqlite_path) as sqlite_conn:
                df = pd.read_sql_query(f"SELECT * FROM \"{table_name}\"", sqlite_conn)
                
                for col_name in df.columns:
                    if df[col_name].dtype == 'object' or 'datetime' in str(df[col_name].dtype):
                        df[col_name] = df[col_name].apply(lambda x: str(x) if pd.notnull(x) else None)
                    else:
                        df[col_name] = df[col_name].where(pd.notnull(df[col_name]), None)
                
                if not df.empty:
                    con.execute(f"INSERT INTO {full_table_name} SELECT * FROM df")
                    print(f"[ERROR] {e}")
                else:
                    print("Empty")
                    
        except Exception as e:
            print(f"FAILED! Error: {e}")

def main():
    if not os.path.exists(ROOT_DIR):
        print(f"[ERROR] Directory does not exist: {ROOT_DIR}")
        return

    con = duckdb.connect(DUCKDB_FILE)

    target_dbs = [
        "california_schools",'european_football_2'
    ]

    for db_folder in target_dbs:
        folder_path = os.path.join(ROOT_DIR, db_folder)
        sqlite_file = os.path.join(folder_path, f"{db_folder}.sqlite")
        if os.path.exists(sqlite_file):
            transfer_database(con, db_folder, sqlite_file)
        else:
            print(f"[SKIP] File not found: {sqlite_file}")

    con.close()
    print("[INFO] Operation status updated.")

if __name__ == "__main__":
    main()
