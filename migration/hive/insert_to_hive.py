import sqlite3
import os
import csv
import subprocess
import re
import time

DOCKER_NAMENODE = "namenode"
DOCKER_HIVE = "hive-server"

BIRD_ROOT = os.getenv('UNIQL_BIRD_DB_ROOT', '<BIRD_DEV_DATABASES>')
HDFS_ROOT_DIR = "/user/hive/warehouse"

DATABASES = ['california_schools', 'card_games', 'european_football_2', 'formula_1', 'student_club', 'thrombosis_prediction', 'toxicology', 'superhero', 'codebase_community', 'debit_card_specializing', 'financial']
# ===========================================

CSV_DELIMITER = "\x01"

def run_docker_cmd(cmd, container=None):
    """Migration helper."""
    if container:
        full_cmd = f'docker exec -i {container} {cmd}'
    else:
        full_cmd = cmd
        
    # print(f"Running: {full_cmd}")
    ret = subprocess.run(full_cmd, shell=True, capture_output=True, text=True, encoding='utf-8', errors='ignore')
    if ret.returncode != 0:
        if "WARN" in ret.stderr and "Error" not in ret.stderr:
            pass
        else:
            print(f"  [Cmd Error]: {ret.stderr.strip()}")
    return ret.returncode == 0

def run_hive_sql(sql):
    """
    Migration helper.
    Migration helper.
    """
    with open("temp_exec.hql", "w", encoding="utf-8") as f:
        f.write(sql)
    
    subprocess.run(f"docker cp temp_exec.hql {DOCKER_HIVE}:/tmp/temp_exec.hql", shell=True)
    
    cmd = "hive -S -f /tmp/temp_exec.hql"
    return run_docker_cmd(cmd, DOCKER_HIVE)

def map_sqlite_to_hive(sqlite_type):
    """Migration helper."""
    st = sqlite_type.upper()
    if 'DATETIME' in st or 'TIMESTAMP' in st or 'DATE' in st or 'TIME' in st:
        return 'STRING'
    if 'INT' in st: return 'INT'
    if 'REAL' in st or 'FLOA' in st or 'DOUB' in st: return 'DOUBLE'
    if 'BOOL' in st: return 'BOOLEAN'
    return 'STRING'

def clean_col_name(name):
    """Migration helper."""
    clean = re.sub(r'[^a-zA-Z0-9_]', '_', name).lower()
    clean = re.sub(r'_+', '_', clean)
    clean = clean.strip('_')
    if not clean: clean = "col_unknown"
    if clean[0].isdigit():
        clean = "col_" + clean
    if clean in ['order', 'group', 'user', 'date', 'timestamp', 'interval', 'from', 'to', 'select', 'table']:
        clean = f"{clean}_col"
    return clean

def clean_data_for_csv(val):
    """Migration helper."""
    if val is None:
        return r'\N'
    
    val = str(val)
    
    # Keep content as intact as possible; only normalize row-breaking
    # characters and the chosen control-character delimiter.
    val = val.replace('\n', ' ').replace('\r', '')
    val = val.replace(CSV_DELIMITER, ' ')
    return val

def check_hive_ready():
    """Migration helper."""
    print("[INFO] Operation status updated.")
    for i in range(30):
        if run_hive_sql("SELECT 1;"):
            print("[INFO] Operation status updated.")
            return True
        print(f"[ERROR] {e}")
        time.sleep(5)
    return False

def main():
    if not check_hive_ready():
        print("[INFO] Operation status updated.")
        return

    run_docker_cmd(f"hdfs dfs -mkdir -p {HDFS_ROOT_DIR}", DOCKER_NAMENODE)

    for db_name in DATABASES:
        sqlite_file = os.path.join(BIRD_ROOT, db_name, f'{db_name}.sqlite')
        if not os.path.exists(sqlite_file):
            print(f"[INFO] Processing database: {db_name}")
            continue

        print(f"[INFO] Processing database: {db_name}")
        
        safe_db_name = clean_col_name(db_name)
        
        run_hive_sql(f"CREATE DATABASE IF NOT EXISTS {safe_db_name};")

        sqlite_conn = sqlite3.connect(sqlite_file)
        sq_cursor = sqlite_conn.cursor()
        sq_cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row[0] for row in sq_cursor.fetchall()]

        for table in tables:
            if table.startswith('sqlite_'): continue
            
            hive_table = clean_col_name(table)
            print(f"[INFO] Processing database: {db_name}")

            sq_cursor.execute(f'PRAGMA table_info("{table}")')
            cols_info = sq_cursor.fetchall()
            
            col_defs = []
            for col in cols_info:
                c_name = clean_col_name(col[1])
                c_type = map_sqlite_to_hive(col[2])
                col_defs.append(f"`{c_name}` {c_type}")
            
            sq_cursor.execute(f'SELECT * FROM "{table}"')
            rows = sq_cursor.fetchall()
            
            if not rows:
                print("[INFO] Operation status updated.")
                continue

            csv_file = f"{hive_table}.csv"
            with open(csv_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f, delimiter=CSV_DELIMITER, quoting=csv.QUOTE_NONE, escapechar='\\')
                
                for row in rows:
                    writer.writerow([clean_data_for_csv(v) for v in row])

            hdfs_path = f"{HDFS_ROOT_DIR}/{safe_db_name}.db/{hive_table}"
            
            run_docker_cmd(f"hdfs dfs -rm -r -f {hdfs_path}", DOCKER_NAMENODE)
            run_docker_cmd(f"hdfs dfs -mkdir -p {hdfs_path}", DOCKER_NAMENODE)
            
            subprocess.run(f"docker cp {csv_file} {DOCKER_NAMENODE}:/tmp/{csv_file}", shell=True)
            run_docker_cmd(f"hdfs dfs -put -f /tmp/{csv_file} {hdfs_path}/data.csv", DOCKER_NAMENODE)
            
            run_docker_cmd(f"rm /tmp/{csv_file}", DOCKER_NAMENODE)
            if os.path.exists(csv_file): os.remove(csv_file)

            create_hql = f"""
            USE {safe_db_name};
            DROP TABLE IF EXISTS {hive_table};
            CREATE EXTERNAL TABLE {hive_table} (
                {', '.join(col_defs)}
            )
            ROW FORMAT DELIMITED
            FIELDS TERMINATED BY '\\001'
            ESCAPED BY '\\\\'
            STORED AS TEXTFILE
            LOCATION '{hdfs_path}'
            TBLPROPERTIES ('serialization.null.format'='\\N');
            """
            
            run_hive_sql(create_hql)

        sqlite_conn.close()
    
    print("[INFO] Operation status updated.")

if __name__ == "__main__":
    main()
