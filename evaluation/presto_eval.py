import subprocess
import uuid
import json
import sqlite3
import datetime
from decimal import Decimal
import math
import re
import time
from dateutil import parser as date_parser
import os

DOCKER_PRESTO_CONTAINER = "presto-coordinator"

# Dialect-specific evaluation step.
QUERY_DELAY_SECONDS = 0.5          # Delay between queries in seconds.
CONTAINER_CHECK_INTERVAL = 5       # Polling interval after container restart.
CONTAINER_MAX_WAIT = 120           # Maximum wait time for container readiness.
CONTAINER_RESTART_RETRIES = 3      # Maximum container restart attempts.


def check_container_running():
    """Check whether the Presto container is running."""
    try:
        ret = subprocess.run(
            f"docker inspect --format='{{{{.State.Running}}}}' {DOCKER_PRESTO_CONTAINER}",
            shell=True, capture_output=True, text=True, timeout=10
        )
        return ret.stdout.strip().strip("'") == "true"
    except Exception:
        return False


def wait_for_presto_ready(timeout=CONTAINER_MAX_WAIT):
    """Wait until the Presto service accepts queries."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            ret = subprocess.run(
                f"docker exec {DOCKER_PRESTO_CONTAINER} /opt/presto-cli --server localhost:8080 --execute 'SELECT 1'",
                shell=True, capture_output=True, text=True, timeout=15
            )
            if ret.returncode == 0 and '1' in ret.stdout:
                return True
        except Exception:
            pass
        time.sleep(CONTAINER_CHECK_INTERVAL)
    return False


def restart_container():
    """Restart the Presto container and wait until it is ready."""
    print(f"[WARN] Presto container is not running, attempting restart...")
    try:
        subprocess.run(f"docker start {DOCKER_PRESTO_CONTAINER}", shell=True, timeout=30)
    except Exception as e:
        print(f"[ERROR] Failed to start container: {e}")
        return False
    
    print(f"[INFO] Waiting for Presto to be ready (max {CONTAINER_MAX_WAIT}s)...")
    if wait_for_presto_ready():
        print(f"[INFO] Presto container is back online!")
        return True
    else:
        print(f"[ERROR] Presto container failed to become ready after restart.")
        return False


def ensure_container_healthy():
    """Ensure the Presto container is running, restarting it if needed."""
    if check_container_running():
        return True
    
    for attempt in range(CONTAINER_RESTART_RETRIES):
        print(f"[INFO] Restart attempt {attempt + 1}/{CONTAINER_RESTART_RETRIES}...")
        if restart_container():
            return True
        time.sleep(CONTAINER_CHECK_INTERVAL)
    
    print(f"[ERROR] All restart attempts failed!")
    return False

class PrestoEvaluator:
    def __init__(self, db_path, presto_gt, presto_pred):
        self.db_path = db_path
        self.presto_gt = presto_gt
        self.presto_pred = presto_pred
        self.host = 'localhost'
        self.port = 8080
        self.user = 'presto'
        self.catalog = 'hive'
        
    def clean_name(self, name):
        """Clean name to match Presto/Hive schema naming rules"""
        clean = re.sub(r'[^a-zA-Z0-9_]', '_', name).lower()
        clean = re.sub(r'_+', '_', clean)
        clean = clean.strip('_')
        if not clean: clean = "col_unknown"
        if clean[0].isdigit():
            clean = "col_" + clean
        if clean in ['order', 'group', 'user', 'date', 'timestamp', 'interval', 'from', 'to', 'select', 'table']:
            clean = f"{clean}_col"
        return clean

    def normalize_row(self, row):
        """Data normalization"""
        new_row = []
        for val in row:
            if isinstance(val, str) and (val.strip() == r'\N' or val.strip() == 'NULL'):
                val = None

            if val is None:
                new_row.append(None)
                continue
            try:
                if '.' in str(val):
                    new_row.append(round(float(val), 3))
                    continue
                else:
                    new_row.append(float(int(val)))
                    continue
            except: pass
            val_str = str(val).strip()
            time_pattern = r'^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?$'
            if re.match(time_pattern, val_str):
                try:
                    dt = date_parser.parse(val_str)
                    new_row.append(dt.strftime('%Y-%m-%d %H:%M:%S'))
                    continue
                except: pass
            new_row.append(val_str)
        return tuple(new_row)

    def presto_query(self, query):
        """
        Execute Presto query via Docker CLI
        With delay and container health check
        """
        # Dialect-specific evaluation step.
        time.sleep(QUERY_DELAY_SECONDS)
        
        # Dialect-specific evaluation step.
        if not ensure_container_healthy():
            return [f"Presto Error: Container {DOCKER_PRESTO_CONTAINER} is not running and restart failed"]
        
        # 1. Schema Name
        db_name = os.path.splitext(os.path.basename(self.db_path))[0]
        safe_db_name = self.clean_name(db_name)
        
        # 2. Preprocess SQL. Keep line breaks so a leading `--` comment
        # does not comment out the SELECT that follows on the next line.
        query = query.strip()
        if not query.endswith(';'): 
            query += ';'
            
        # 3. Write to temp file
        temp_filename = f"temp_eval_{uuid.uuid4().hex}.sql"
        
        try:
            # Write to local file
            with open(temp_filename, "w", encoding="utf-8") as f:
                f.write(query)
                
            # Copy to container
            subprocess.run(f"docker cp {temp_filename} {DOCKER_PRESTO_CONTAINER}:/tmp/{temp_filename}", shell=True)
            
            # 4. Construct command
            # -f: execute file
            # --output-format TSV
            cmd = f'docker exec -i {DOCKER_PRESTO_CONTAINER} /opt/presto-cli ' \
                  f'--server localhost:8080 --catalog hive --schema {safe_db_name} ' \
                  f'-f /tmp/{temp_filename} ' \
                  f'--output-format TSV'
            
            # Execute
            ret = subprocess.run(cmd, shell=True, capture_output=True, text=True, encoding='utf-8', errors='ignore', timeout=120)
            
            # Clean up container file
            subprocess.run(f"docker exec -i {DOCKER_PRESTO_CONTAINER} rm /tmp/{temp_filename}", shell=True)
            
            if ret.returncode != 0:
                return [f"Presto Error: {ret.stderr.strip()}"]
            
            # 5. Parse results
            output = ret.stdout
            if output.endswith('\n'):
                output = output[:-1]
                
            if not output:
                return []
                
            rows = []
            for line in output.split('\n'):
                vals = line.split('\t')
                cleaned_vals = []
                for v in vals:
                    if v == '':
                        cleaned_vals.append(None)
                    else:
                        cleaned_vals.append(v) 
                rows.append(tuple(cleaned_vals))
                
            return rows
                
        except Exception as e:
            return [f"Presto Error: {str(e)}"]
        finally:
            # Clean up local file
            if os.path.exists(temp_filename):
                os.remove(temp_filename)

    def rows_are_equal(self, row_a, row_b, tolerance=1e-3):
        """Compare two rows"""
        if len(row_a) != len(row_b): return False
        for val_a, val_b in zip(row_a, row_b):
            if isinstance(val_a, float) and isinstance(val_b, float):
                if math.isnan(val_a) and math.isnan(val_b): continue
                if abs(val_a - val_b) > tolerance: return False
            elif val_a is None or val_b is None:
                if val_a != val_b: return False
            else:
                if val_a != val_b: return False
        return True

    def clean_sql(self, sql):
        cleaned = sql.strip()
        if cleaned.endswith(";"):
            cleaned = cleaned[:-1].rstrip()
        return cleaned

    def check_result_same(self):
        presto_gt = self.clean_sql(self.presto_gt)
        presto_pred = self.clean_sql(self.presto_pred)
        
        result_gt = self.presto_query(presto_gt)
        result_pred = self.presto_query(presto_pred)
        
        if isinstance(result_gt, list) and len(result_gt) == 1 and str(result_gt[0]).startswith("Presto Error"):
            return False, result_gt, result_pred
        if isinstance(result_pred, list) and len(result_pred) == 1 and str(result_pred[0]).startswith("Presto Error"):
            return False, result_gt, result_pred
            
        norm_gt = [self.normalize_row(row) for row in result_gt]
        norm_pred = [self.normalize_row(row) for row in result_pred]

        if len(norm_gt) != len(norm_pred):
            is_same = False
        else:
            check_order = "order by" in (self.presto_gt.lower() + self.presto_pred.lower())
            
            if check_order:
                # Ordered comparison
                is_same = True
                for r_m, r_s in zip(norm_gt, norm_pred):
                    if not self.rows_are_equal(r_m, r_s):
                        is_same = False
                        break
            else:
                # Unordered comparison
                pool_pred = list(norm_pred)
                is_same = True
                for r_m in norm_gt:
                    found = False
                    for idx, r_s in enumerate(pool_pred):
                        if self.rows_are_equal(r_m, r_s):
                            pool_pred.pop(idx)
                            found = True
                            break
                    if not found:
                        is_same = False
                        break
        return is_same, result_gt, result_pred
