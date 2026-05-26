import subprocess
import math
import re
import os
from dateutil import parser as date_parser

try:
    import sqlglot
    from sqlglot import exp
    HAS_SQLGLOT = True
except ImportError:
    HAS_SQLGLOT = False


SPARK_CONTAINER = "spark"
BEELINE_BIN = "/opt/spark/bin/beeline"
JDBC_URL = "jdbc:hive2://localhost:10000"
QUERY_TIMEOUT = 30  # seconds per query


def _clean_spark_name(name):
    """Match insert_to_spark_v20260423.py clean_name logic."""
    clean = re.sub(r'[^a-zA-Z0-9_]', '_', name)
    clean = re.sub(r'_+', '_', clean).strip('_')
    if not clean:
        clean = "col_unknown"
    if clean[0].isdigit():
        clean = "col_" + clean
    return clean


def clean_spark_sql(query):
    """Walk AST and clean all table/column names to match migrated Spark schema."""
    if not HAS_SQLGLOT:
        return query
    try:
        ast = sqlglot.parse_one(query, read='spark')
        for node in ast.walk():
            if isinstance(node, (exp.Table, exp.Column)):
                if isinstance(node.this, exp.Star):
                    continue
                clean = _clean_spark_name(node.name)
                node.set("this", exp.Identifier(this=clean, quoted=True))
        return ast.sql(dialect='spark')
    except Exception:
        return query


class SparkEvaluator:
    def __init__(self, db_path, spark_gt, spark_pred):
        self.db_path = db_path
        self.spark_gt = spark_gt
        self.spark_pred = spark_pred

    def normalize_row(self, row):
        new_row = []
        for val in row:
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
            except:
                pass
            val_str = str(val).strip()
            time_pattern = r'^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?$'
            if re.match(time_pattern, val_str):
                try:
                    dt = date_parser.parse(val_str)
                    new_row.append(dt.strftime('%Y-%m-%d %H:%M:%S'))
                    continue
                except:
                    pass
            new_row.append(val_str)
        return tuple(new_row)

    def spark_query(self, query):
        db_name = os.path.splitext(os.path.basename(self.db_path))[0].lower()

        query = query.replace('\n', ' ').strip()
        if query.endswith(';'):
            query = query[:-1].strip()

        # Write SQL to temp file to avoid bash escaping issues
        import tempfile
        full_sql = f"USE {db_name};\n{query};\n"
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode='w', suffix='.sql', delete=False, encoding='utf-8'
            ) as tmp:
                tmp.write(full_sql)
                tmp_path = tmp.name

            container_file = f"/tmp/_eval_{os.path.basename(tmp_path)}.sql"

            # Copy file to container
            subprocess.run(
                ['docker', 'cp', tmp_path, f'{SPARK_CONTAINER}:{container_file}'],
                capture_output=True, timeout=10,
            )

            # Execute via beeline -f (file mode, no SQL escaping issues)
            beeline_cmd = (
                f"{BEELINE_BIN} -u '{JDBC_URL}' -n spark "
                f"--silent=true --showHeader=false --outputformat=tsv2 "
                f"--showWarnings=false "
                f"-f {container_file}"
            )
            cmd = ['docker', 'exec', '-i', SPARK_CONTAINER, 'bash', '-c', beeline_cmd]

            ret = subprocess.run(
                cmd,
                capture_output=True,
                text=False,
                timeout=QUERY_TIMEOUT,
            )

            # Clean up container file
            subprocess.run(
                ['docker', 'exec', SPARK_CONTAINER, 'rm', '-f', container_file],
                capture_output=True, timeout=5,
            )

            stdout = ret.stdout.decode('utf-8', errors='replace')
            stderr = ret.stderr.decode('utf-8', errors='replace')

            # Filter beeline/Spark log noise from stderr
            log_keywords = [
                'Connecting to', 'Connected to', 'Driver:',
                'Beeline version', 'Transaction isolation',
                'closed', 'INFO', 'WARN', 'jdbc:hive2',
                'No current connection',
            ]
            real_stderr_lines = []
            for line in stderr.split('\n'):
                if any(kw in line for kw in log_keywords):
                    continue
                if line.strip():
                    real_stderr_lines.append(line)
            real_stderr = '\n'.join(real_stderr_lines)

            if ret.returncode != 0:
                err = real_stderr[:300] if real_stderr else f"Beeline failed (rc={ret.returncode})"
                return [f"Spark Error: {err}"]

            output = stdout.strip()
            if not output:
                return []

            rows = []
            for line in output.split('\n'):
                line = line.strip()
                if not line:
                    continue
                # Strip beeline prompt prefix: "0: jdbc:hive2://...> "
                line = re.sub(r'^\d+:\s*jdbc:hive2://\S+\>\s*', '', line).strip()
                if not line:
                    continue
                vals = line.split('\t')
                cleaned = []
                for v in vals:
                    v_clean = v.strip()
                    if v_clean == 'NULL' or v_clean == '':
                        cleaned.append(None)
                    else:
                        cleaned.append(v)
                if cleaned:
                    rows.append(tuple(cleaned))
            return rows

        except subprocess.TimeoutExpired:
            return ["Spark Error: Query timeout"]
        except Exception as e:
            return [f"Spark Error: {str(e)}"]
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except:
                    pass

    def rows_are_equal(self, row_a, row_b, tolerance=1e-3):
        if len(row_a) != len(row_b):
            return False
        for val_a, val_b in zip(row_a, row_b):
            if isinstance(val_a, float) and isinstance(val_b, float):
                if math.isnan(val_a) and math.isnan(val_b):
                    continue
                if abs(val_a - val_b) > tolerance:
                    return False
            elif val_a is None or val_b is None:
                if val_a != val_b:
                    return False
            else:
                if val_a != val_b:
                    return False
        return True

    def clean_sql(self, sql):
        cleaned = sql.strip()
        if cleaned.endswith(";"):
            cleaned = cleaned[:-1].rstrip()
        # Clean table/column names to match migrated Spark schema
        cleaned = clean_spark_sql(cleaned)
        return cleaned

    def check_result_same(self):
        spark_gt = self.clean_sql(self.spark_gt)
        spark_pred = self.clean_sql(self.spark_pred)

        result_gt = self.spark_query(spark_gt)
        result_pred = self.spark_query(spark_pred)

        if isinstance(result_gt, list) and len(result_gt) == 1 and str(result_gt[0]).startswith("Spark Error"):
            return False, result_gt, result_pred
        if isinstance(result_pred, list) and len(result_pred) == 1 and str(result_pred[0]).startswith("Spark Error"):
            return False, result_gt, result_pred

        norm_gt = [self.normalize_row(row) for row in result_gt]
        norm_pred = [self.normalize_row(row) for row in result_pred]

        if len(norm_gt) != len(norm_pred):
            is_same = False
        else:
            check_order = "order by" in (self.spark_gt.lower() + self.spark_pred.lower())
            if check_order:
                is_same = True
                for r_m, r_s in zip(norm_gt, norm_pred):
                    if not self.rows_are_equal(r_m, r_s):
                        is_same = False
                        break
            else:
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
