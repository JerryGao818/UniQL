import os
import sqlite3
import pymssql
import mysql.connector
import psycopg2
import oracledb
import re
import subprocess
from config import MYSQL_CONFIG, MSSQL_CONFIG, PG_CONFIG, ORACLE_DSN, ORACLE_PASSWORD, DB_ROOT_DIR, HIVE_CONFIG

HIVE_QUERY_TIMEOUT_SEC = int(os.getenv("HIVE_QUERY_TIMEOUT_SEC", "20"))

class DBManager:
    def __init__(self):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        # Resolve DB root relative to this file, not process cwd.
        self.root_dir = os.path.abspath(os.path.join(base_dir, DB_ROOT_DIR))

        # Fallback roots for different local layouts.
        self._sqlite_root_candidates = [
            self.root_dir,
            os.path.abspath(os.path.join(base_dir, '../../Bird_dataset/dev/dev_databases')),
            os.path.abspath(os.path.join(base_dir, '../../Bird_dataset/dev')),
        ]

    def _resolve_sqlite_db_path(self, db_name):
        for root in self._sqlite_root_candidates:
            db_path = os.path.join(root, db_name, f"{db_name}.sqlite")
            if os.path.exists(db_path):
                return db_path
        # Default to primary path for clear error message if not found.
        return os.path.join(self.root_dir, db_name, f"{db_name}.sqlite")

    def get_connection(self, db_type, db_name):
        """
        Get database connection.
        db_type: sqlite, mysql, postgresql, oracle, mssql (case insensitive)
        db_name: database name (or user for Oracle, db_id for SQLite)
        """
        dt = db_type.lower()
        
        try:
            if 'sqlite' in dt:
                db_path = self._resolve_sqlite_db_path(db_name)
                return sqlite3.connect(db_path)
            
            elif 'mysql' in dt:
                return mysql.connector.connect(
                    database=db_name,
                    **MYSQL_CONFIG
                )
            
            elif 'postgres' in dt:
                return psycopg2.connect(
                    dbname=db_name,
                    **PG_CONFIG
                )
            
            elif 'mssql' in dt:
                return pymssql.connect(
                    database=db_name,
                    **MSSQL_CONFIG
                )
            
            elif 'oracle' in dt:
                # Oracle uses user/schema as DB container
                return oracledb.connect(
                    user=db_name.upper(),
                    password=ORACLE_PASSWORD,
                    dsn=ORACLE_DSN
                )
            elif 'hive' in dt:
                 # Hive uses Docker execution, returns dummy connection object to pass check
                 return "HIVE_DOCKER_CONNECTION"
            else:
                raise ValueError(f"Unsupported database type: {db_type}")
        except Exception as e:
            # print(f"Connection failed for {db_type} - {db_name}: {e}")
            return None

    def execute_query(self, db_type, db_name, sql):
        """
        Execute SQL query and return results.
        Returns: (result_list, error_message)
        """
        conn = self.get_connection(db_type, db_name)
        if not conn:
            return None, f"Connection failed to {db_type}/{db_name}"
        
        dt = db_type.lower()
        
        # Hive Special Handling (Docker Exec)
        if 'hive' in dt:
             return self._execute_hive(db_name, sql)

        cursor = None
        try:
            if 'oracle' in dt:
                # Specialized Oracle Type Handler for LOBs
                def OutputTypeHandler(cursor, name, default_type, size, precision, scale):
                    if default_type == oracledb.CLOB:
                        return cursor.var(str, arraysize=cursor.arraysize)
                    if default_type == oracledb.BLOB:
                        return cursor.var(bytes, arraysize=cursor.arraysize)
                conn.outputtypehandler = OutputTypeHandler
                conn.autocommit = True # Safe for select
                
                cursor = conn.cursor()
                cursor.execute("ALTER SESSION SET NLS_DATE_FORMAT = 'YYYY-MM-DD HH24:MI:SS'")
                cursor.execute(sql)
            elif 'mysql' in dt:
                 cursor = conn.cursor(dictionary=False)
                 cursor.execute(sql)
            else:
                cursor = conn.cursor()
                cursor.execute(sql)

            # Fetch results
            if sql.strip().upper().startswith(('SELECT', 'WITH', 'SHOW', 'DESC')):
                res = cursor.fetchall()
                return res, None
            else:
                conn.commit()
                return [], None
                
        except Exception as e:
            # print(f"Execution error on {db_type}/{db_name}: {e}") # Optional logging
            return None, str(e)
        finally:
             if cursor:
                 cursor.close()
             if conn:
                 try: conn.close()
                 except: pass

    def _execute_hive(self, db_name, query):
        """
        Execute Hive query via Docker.
        """
        # Normalize BIRD database identifiers to Hive-compatible database names.
        hive_db = re.sub(r'[^a-zA-Z0-9_]', '_', db_name).lower().strip('_')
        if hive_db[0].isdigit(): hive_db = "col_" + hive_db # simplistic prefix
        
        # 2. Preprocess SQL
        query = query.replace('\n', ' ').strip()
        if query.endswith(';'): query = query[:-1]
        
        # 3. Construct Command
        container = HIVE_CONFIG['docker_container']
        cmd = f'docker exec -i {container} hive -S --database {hive_db} -e "{query}"'
        
        try:
            run_kwargs = {
                "shell": True,
                "capture_output": True,
                "text": True,
                "encoding": "utf-8",
                "errors": "ignore",
            }

            # HIVE_QUERY_TIMEOUT_SEC <= 0 means no timeout limit.
            if HIVE_QUERY_TIMEOUT_SEC > 0:
                run_kwargs["timeout"] = HIVE_QUERY_TIMEOUT_SEC

            ret = subprocess.run(cmd, **run_kwargs)
            
            # Log filtering
            def filter_logs(log_text):
                lines = log_text.split('\n')
                clean_lines = []
                for line in lines:
                    if "SLF4J" in line or "INFO" in line or "WARN" in line: continue
                    if line.strip() == "": continue
                    clean_lines.append(line)
                return "\n".join(clean_lines)

            real_error = filter_logs(ret.stderr)
            if ret.returncode != 0:
                err_msg = real_error if real_error else (ret.stderr.split('\n')[-1] if ret.stderr else "Unknown Hive Error")
                return None, err_msg
            
            output = ret.stdout.strip()
            if not output:
                return [], None
                
            rows = []
            for line in output.split('\n'):
                vals = line.split('\t')
                cleaned_vals = []
                for v in vals:
                    v_clean = v.strip()
                    if v_clean in ('\\N', '\\\\N', 'NULL'):
                        cleaned_vals.append(None)
                    else:
                        cleaned_vals.append(v)
                rows.append(tuple(cleaned_vals))
                
            return rows, None
            
        except subprocess.TimeoutExpired:
            return None, f"Hive query timeout after {HIVE_QUERY_TIMEOUT_SEC}s"
        except Exception as e:
            return None, str(e)

    def get_schema(self, db_type, db_name):
        """
        Get formatted schema string for the database.
        """
        dt = db_type.lower()
        conn = self.get_connection(db_type, db_name)
        if not conn and 'hive' not in dt: # Hive conn is string
            return f"Error: Could not connect to {db_type} database {db_name}"
            
        schema_str = ""
        try:
            if 'mssql' in dt:
                cursor = conn.cursor()
                sql = """
                SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE 
                FROM INFORMATION_SCHEMA.COLUMNS 
                WHERE TABLE_SCHEMA = 'dbo' 
                ORDER BY TABLE_NAME, ORDINAL_POSITION
                """
                cursor.execute(sql)
                rows = cursor.fetchall()
                conn.close()
                
            elif 'mysql' in dt:
                cursor = conn.cursor()
                sql = """
                SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = %s
                ORDER BY TABLE_NAME, ORDINAL_POSITION
                """
                cursor.execute(sql, (db_name,))
                rows = cursor.fetchall()
                conn.close()

            elif 'postgres' in dt:
                cursor = conn.cursor()
                sql = """
                SELECT table_name, column_name, data_type 
                FROM information_schema.columns 
                WHERE table_schema = 'public' 
                ORDER BY table_name, ordinal_position;
                """
                cursor.execute(sql)
                rows = cursor.fetchall()
                conn.close()
                
            elif 'oracle' in dt:
                cursor = conn.cursor()
                sql = """
                SELECT table_name, column_name, data_type 
                FROM user_tab_columns 
                ORDER BY table_name, column_id
                """
                cursor.execute(sql)
                rows = cursor.fetchall()
                conn.close()
            
            elif 'sqlite' in dt:
                cursor = conn.cursor()
                # Generic SQLite schema extraction
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
                tables = [row[0] for row in cursor.fetchall()]
                rows = []
                for table in tables:
                    cursor.execute(f"PRAGMA table_info(\"{table}\")")
                    cols = cursor.fetchall()
                    for col in cols:
                        # cid, name, type, notnull, dflt_value, pk
                        rows.append((table, col[1], col[2]))
                conn.close()
            
            elif 'hive' in dt:
                # Infer Hive schema from the aligned local SQLite source file.
                try: 
                     db_path = os.path.join(self.root_dir, db_name, f"{db_name}.sqlite")
                     return self._simulate_hive_schema_from_sqlite(db_path)
                except Exception as e:
                     return f"Hive Schema Error: {e}"

            else:
                return "Unsupported DB Type for Schema"

            # Format the schema
            current_table = None
            for row in rows:
                table_name = row[0]
                col_name = row[1]
                data_type = row[2]
                
                if table_name != current_table:
                    if current_table:
                        schema_str += ")\n"
                    schema_str += f"Table: {table_name} (\n"
                    current_table = table_name
                else:
                    schema_str += ",\n"
                
                schema_str += f"  {col_name} {data_type}"
            
            if current_table:
                schema_str += "\n)"

        except Exception as e:
            schema_str = f"Error fetching schema: {e}"
            
        return schema_str

    def _simulate_hive_schema_from_sqlite(self, db_path):
        """
        Helper to simulate Hive schema from SQLite file (copied logic).
        """
        # Helper inner function for cleaning names
        def clean_col_name(name):
            clean = re.sub(r'[^a-zA-Z0-9_]', '_', name).lower()
            clean = re.sub(r'_+', '_', clean)
            clean = clean.strip('_')
            if not clean: clean = "col_unknown"
            if clean[0].isdigit(): clean = "col_" + clean
            if clean in ['order', 'group', 'user', 'date', 'timestamp', 'interval', 'from', 'to', 'select', 'table']:
                clean = f"{clean}_col"
            return clean

        def map_sqlite_to_hive_type(sqlite_type):
            st = sqlite_type.upper()
            if 'INT' in st: return 'INT'
            if 'REAL' in st or 'FLOA' in st or 'DOUB' in st: return 'DOUBLE'
            if 'BOOL' in st: return 'BOOLEAN'
            if 'DATE' in st: return 'DATE'
            if 'TIME' in st: return 'TIMESTAMP'
            return 'STRING'

        if not os.path.exists(db_path):
            return f"Error: SQLite source file for Schema simulation not found at {db_path}"

        schema_str = ""
        conn_lite = sqlite3.connect(db_path)
        try:
            cursor_lite = conn_lite.cursor()
            cursor_lite.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = [row[0] for row in cursor_lite.fetchall()]

            for table in tables:
                if table.startswith('sqlite_'): continue
                
                hive_table = clean_col_name(table)
                schema_str += f"\nTable: `{hive_table}`\n"
                
                cursor_lite.execute(f'PRAGMA table_info("{table}")')
                cols = cursor_lite.fetchall()
                for col in cols:
                     hive_col = clean_col_name(col[1])
                     hive_type = map_sqlite_to_hive_type(col[2])
                     schema_str += f"  - `{hive_col}` ({hive_type})\n"
        finally:
            conn_lite.close()
            
        return schema_str.strip()


