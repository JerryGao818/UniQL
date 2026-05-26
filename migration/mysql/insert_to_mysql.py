import os
from sqlalchemy import create_engine, MetaData, inspect
from sqlalchemy.types import VARCHAR, Text, String, Boolean
from sqlalchemy import text
from sqlalchemy.schema import Index
from sqlalchemy.exc import OperationalError


ROOT_DIR = os.getenv('UNIQL_BIRD_DB_ROOT', '<BIRD_DEV_DATABASES>')

MYSQL_USER = os.getenv("UNIQL_MYSQL_USER", "root")
MYSQL_PASS = os.getenv("UNIQL_MYSQL_PASSWORD", "<MYSQL_PASSWORD>")
MYSQL_HOST = os.getenv("UNIQL_MYSQL_HOST", "localhost")

def get_mysql_engine_root():
    return create_engine(f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASS}@{MYSQL_HOST}")

def get_mysql_engine_db(db_name):
    connect_args = {
        "init_command": "SET SESSION sql_mode='NO_ENGINE_SUBSTITUTION'"
    }
    return create_engine(
        f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASS}@{MYSQL_HOST}/{db_name}?charset=utf8mb4",
        connect_args=connect_args
    )

def transfer_database(folder_name, sqlite_path):
    print(f"[INFO] Processing database: {folder_name}")
    
    sqlite_engine = create_engine(f"sqlite:///{sqlite_path}")
    
    mysql_root = get_mysql_engine_root()
    with mysql_root.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS `{folder_name}`"))
        conn.execute(text(f"CREATE DATABASE `{folder_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci"))
    mysql_root.dispose()
    
    mysql_engine = get_mysql_engine_db(folder_name)
    
    metadata = MetaData()
    
    try:
        metadata.reflect(bind=sqlite_engine, views=False)
    except:
        metadata.reflect(bind=sqlite_engine)
    
    referenced_columns = set()
    for table in metadata.sorted_tables:
        for column in table.columns:
            for fk in column.foreign_keys:
                if fk.column is not None: referenced_columns.add(fk.column)

    for table in metadata.sorted_tables:
        cols_to_convert = set()
        for constraint in table.constraints:
            if hasattr(constraint, 'columns'):
                for col in constraint.columns: cols_to_convert.add(col.name)
        for index in table.indexes:
            for col in index.columns: cols_to_convert.add(col.name)

        for column in table.columns:
            lower_name = column.name.lower()
            if any(k in lower_name for k in ['id', 'uuid', 'code', 'url', 'email', 'name', 'type']):
                cols_to_convert.add(column.name)
            if column.primary_key or column.foreign_keys:
                cols_to_convert.add(column.name)
            if column in referenced_columns:
                cols_to_convert.add(column.name)

            if isinstance(column.type, (Text, String)):
                if column.name in cols_to_convert:
                    column.type = VARCHAR(255)
            
            column.server_default = None
            
            if isinstance(column.type, Boolean):
                from sqlalchemy.dialects.mysql import TINYINT
                column.type = TINYINT(1)

        for column in table.columns:
            need_index = False
            if column in referenced_columns: need_index = True
            if isinstance(column.type, VARCHAR) and not column.primary_key:
                if any(k in column.name.lower() for k in ['uuid', 'id', 'code']): need_index = True
            
            if need_index:
                has_index = False
                if column.primary_key: has_index = True
                for idx in table.indexes:
                    if column.name in idx.columns:
                        has_index = True; break
                if not has_index:
                    idx_name = f"idx_{table.name}_{column.name}"[:60]
                    Index(idx_name, column)

    # ===============================================

    with mysql_engine.connect() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS=0;"))
        
        print("[INFO] Operation status updated.")
        
        for table in metadata.sorted_tables:
            try:
                table.create(mysql_engine)
            except OperationalError as e:
                if "1050" in str(e):
                    print(f"[ERROR] {e}")
                    continue
                else:
                    print(f"[ERROR] {e}")
                    return

        for table in metadata.sorted_tables:
            print("[INFO] Operation status updated.")
            try:
                with sqlite_engine.connect() as sqlite_conn:
                    data_cursor = sqlite_conn.execution_options(stream_results=True).execute(table.select())
                    chunk_size = 1000
                    while True:
                        rows = data_cursor.fetchmany(chunk_size)
                        if not rows: break
                        data_to_insert = [dict(row._mapping) for row in rows]
                        
                        try:
                            conn.execute(table.insert(), data_to_insert)
                        except Exception as insert_err:
                            pass
                        
                    conn.commit()
            except Exception as e:
                print(f"[ERROR] {e}")

        conn.execute(text("SET FOREIGN_KEY_CHECKS=1;"))

    print(f"[INFO] Processing database: {folder_name}")

def main():
    if not os.path.exists(ROOT_DIR):
        print(f"[ERROR] Directory does not exist: {ROOT_DIR}")
        return

    target_dbs = ['european_football_2']

    for db_folder in os.listdir(ROOT_DIR):
        if db_folder in target_dbs:
            folder_path = os.path.join(ROOT_DIR, db_folder)
            if os.path.isdir(folder_path):
                sqlite_file = os.path.join(folder_path, f"{db_folder}.sqlite")
                if os.path.exists(sqlite_file):
                    try:
                        transfer_database(db_folder, sqlite_file)
                    except Exception as e:
                        print(f"[ERROR] {e}")

if __name__ == "__main__":
    main()
