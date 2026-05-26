import json
import sqlite3
import datetime
from decimal import Decimal
import math
import re
from dateutil import parser as date_parser
import oracledb
import os

class OracleEvaluater:
    def __init__(self, db_path, oracle_gt, oracle_pred):
        self.db_path = db_path
        self.oracle_gt = oracle_gt.upper()
        self.oracle_pred = oracle_pred.upper()
        self.admin_user = os.getenv("UNIQL_ORACLE_ADMIN_USER", "SYSTEM")
        self.admin_pass = os.getenv("UNIQL_ORACLE_PASSWORD", "<ORACLE_PASSWORD>")
        self.oracle_dsn = os.getenv("UNIQL_ORACLE_DSN", "localhost:1521/XE")

    def normalize_row(self,row):
        """Normalize values into comparable Python types."""
        new_row = []
        for val in row:
            # Dialect-specific evaluation step.
            if isinstance(val, oracledb.LOB):
                try: val = str(val.read())
                except: pass
            
            if isinstance(val, (int, float, Decimal)):
                try: val = round(float(val), 3)
                except: pass
            elif isinstance(val, (datetime.date, datetime.datetime, datetime.time, datetime.timedelta)):
                if isinstance(val, datetime.datetime):
                    val = val.strftime('%Y-%m-%d %H:%M:%S')
                else:
                    val = str(val)
            elif isinstance(val, bytes):
                try: val = val.decode('utf-8')
                except: pass
            elif isinstance(val, str):
                val = val.strip()
                # Dialect-specific evaluation step.
                time_pattern = r'^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?$'
                if re.match(time_pattern, val):
                    try:
                        dt = date_parser.parse(val)
                        val = dt.strftime('%Y-%m-%d %H:%M:%S')
                    except: pass
            new_row.append(val)
        return tuple(new_row)

    def OutputTypeHandler(self,cursor, name, default_type, size, precision, scale):
        if default_type == oracledb.CLOB:
            return cursor.var(str, arraysize=cursor.arraysize)
        if default_type == oracledb.BLOB:
            return cursor.var(bytes, arraysize=cursor.arraysize)

    def oracle_query(self,query):
        """Execute a dialect-specific query."""
        connection = None
        cursor = None
        db_id = os.path.splitext(os.path.basename(self.db_path))[0]
        try:
            connection = oracledb.connect(
                user=db_id.upper(), 
                password=self.admin_pass, 
                dsn=self.oracle_dsn
            )
            
            # Dialect-specific evaluation step.
            # Dialect-specific evaluation step.
            connection.outputtypehandler = self.OutputTypeHandler
            
            cursor = connection.cursor()
            cursor.execute("ALTER SESSION SET NLS_DATE_FORMAT = 'YYYY-MM-DD HH24:MI:SS'")
            
            cursor.execute(query)
            
            rows = cursor.fetchall()
            return rows
        except oracledb.Error as e:
            return [f"oracle error{e}"]
        finally:
            if cursor: cursor.close()
            if connection: connection.close()
    def clean_sql(self,sql):
        sql = sql.replace('\n',' ').rstrip(";")
        match = re.search(r'\b(SELECT|WITH)\b', sql, re.IGNORECASE)
        if match:
            return sql[match.start():].strip()
        return sql
    def check_result_same(self):
        """Compare normalized query results."""
        oracle_gt = self.clean_sql(self.oracle_gt)
        oracle_pred = self.clean_sql(self.oracle_pred)
        print(oracle_pred)
        result_oracle_gt = self.oracle_query(oracle_gt)
        result_oracle_pred = self.oracle_query(oracle_pred)

        norm_gt = [self.normalize_row(row) for row in result_oracle_gt]
        norm_pred = [self.normalize_row(row) for row in result_oracle_pred]

        if len(norm_gt) != len(norm_pred):
            return False,result_oracle_gt,result_oracle_pred
        
        # Dialect-specific evaluation step.
        def rows_are_equal(row_a, row_b, tolerance=1e-3):
            if len(row_a) != len(row_b): return False
            for val_a, val_b in zip(row_a, row_b):
                if isinstance(val_a, float) and isinstance(val_b, float):
                    if math.isnan(val_a) and math.isnan(val_b): continue
                    if abs(val_a - val_b) > tolerance: return False
                elif val_a is None or val_b is None:
                    if val_a != val_b: return False
                else:
                    if str(val_a) != str(val_b): return False
            return True

        check_order = "order by" in (self.oracle_gt.lower() + self.oracle_pred.lower())
        
        if check_order:
            for r_o, r_s in zip(norm_gt, norm_pred):
                if not rows_are_equal(r_o, r_s): return False,result_oracle_gt,result_oracle_pred
            return True,result_oracle_gt,result_oracle_pred
        else:
            pool_pred = list(norm_pred)
            for r_o in norm_gt:
                found = False
                for idx, r_s in enumerate(pool_pred):
                    if rows_are_equal(r_o, r_s):
                        pool_pred.pop(idx)
                        found = True
                        break
                if not found: return False,result_oracle_gt,result_oracle_pred
            return True,result_oracle_gt,result_oracle_pred
