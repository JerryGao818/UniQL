import os
import sqlite3
import pandas as pd
import clickhouse_connect
from sqlalchemy import create_engine, MetaData, types

ROOT_DIR = os.getenv('UNIQL_BIRD_DB_ROOT', '<BIRD_DEV_DATABASES>')
CH_HOST = "localhost"
CH_PORT = 8124
CH_USER = "default"
CH_PASS = ""

def get_clickhouse_client():
    return clickhouse_connect.get_client(host=CH_HOST, port=CH_PORT, username=CH_USER, password=CH_PASS)

def map_sqlalchemy_type_to_ch(sqla_column):
    """
    Migration helper.
    Migration helper.
    Migration helper.
    """
    t = sqla_column.type
    
    if isinstance(t, types.BigInteger): return "Int64"
    if isinstance(t, types.Integer): return "Int32"
    if isinstance(t, types.SmallInteger): return "Int16"
    
    if isinstance(t, (types.Float, types.Numeric, types.REAL)): return "Float64"
    
    return "String"

def transfer_database(folder_name, sqlite_path):
    print(f"[INFO] Processing database: {folder_name}")
    
    ch_client = get_clickhouse_client()
    
    ch_client.command(f"DROP DATABASE IF EXISTS `{folder_name}`")
    ch_client.command(f"CREATE DATABASE `{folder_name}`")
    
    sqlite_engine = create_engine(f"sqlite:///{sqlite_path}")
    metadata = MetaData()
    metadata.reflect(bind=sqlite_engine)
    
    for table in metadata.sorted_tables:
        table_name = table.name
        print(f"[INFO] Processing table: {table_name}")
        
        columns_gen = []
        pks = []
        for col in table.columns:
            base_type = map_sqlalchemy_type_to_ch(col)
            ch_type = f"Nullable({base_type})" if not col.primary_key else base_type
            columns_gen.append(f"`{col.name}` {ch_type}")
            if col.primary_key:
                pks.append(f"`{col.name}`")
        
        order_by = f"({', '.join(pks)})" if pks else "tuple()"
        create_sql = f"CREATE TABLE `{folder_name}`.`{table_name}` ({', '.join(columns_gen)}) ENGINE = MergeTree() ORDER BY {order_by}"
        ch_client.command(create_sql)
        
        try:
            with sqlite3.connect(sqlite_path) as conn:
                df = pd.read_sql_query(f"SELECT * FROM `{table_name}`", conn)
                
                for col_name in df.columns:
                    if df[col_name].dtype == 'object' or 'datetime' in str(df[col_name].dtype):
                        df[col_name] = df[col_name].apply(lambda x: str(x) if pd.notnull(x) else None)
                
                if not df.empty:
                    ch_client.insert_df(database=folder_name, table=table_name, df=df)
                    print(f"[ERROR] {e}")
                else:
                    print("[INFO] Operation status updated.")
                    
        except Exception as e:
            print(f"[ERROR] {e}")

def main():
    if not os.path.exists(ROOT_DIR):
        print(f"[ERROR] Directory does not exist: {ROOT_DIR}")
        return

    target_dbs = ['superhero', 'codebase_community', 'debit_card_specializing', 
    'financial', 'california_schools', 'card_games', 
    'european_football_2', 'formula_1', 'student_club', 
    'thrombosis_prediction', 'toxicology']

    for db_folder in target_dbs:
        folder_path = os.path.join(ROOT_DIR, db_folder)
        sqlite_file = os.path.join(folder_path, f"{db_folder}.sqlite")
        if os.path.exists(sqlite_file):
            transfer_database(db_folder, sqlite_file)
        else:
            print(f"[SKIP] File not found: {sqlite_file}")

if __name__ == "__main__":
    main()
