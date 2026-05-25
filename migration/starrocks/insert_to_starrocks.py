"""
Migration helper.
==========================================
Migration helper.
Migration helper.
Migration helper.
Migration helper.
"""

import os
import re
import sqlite3
import pymysql

SQLITE_ROOT = "../dev/dev_databases/dev_databases"

DATABASES = [
    'california_schools',
    'card_games', 'european_football_2',
    'formula_1', 'student_club', 'thrombosis_prediction',
    'toxicology', 'superhero', 'codebase_community',
    'debit_card_specializing', 'financial'
]

SR_HOST = "localhost"
SR_PORT = 9030
SR_USER = "root"
SR_PASSWORD = ""

BATCH_SIZE = 1000
# =================================================


def get_sr_connection(db_name=None):
    """Migration helper."""
    return pymysql.connect(
        host=SR_HOST,
        port=SR_PORT,
        user=SR_USER,
        password=SR_PASSWORD,
        database=db_name,
        charset='utf8mb4',
        autocommit=True
    )


def safe_name(name: str) -> str:
    """
    Migration helper.
    Migration helper.
    """
    clean = re.sub(r'[^a-zA-Z0-9_]', '_', name)
    clean = re.sub(r'_+', '_', clean).strip('_')
    if not clean:
        clean = "col_unknown"
    if clean[0].isdigit():
        clean = "col_" + clean
    return f"`{clean}`"


def map_type(sqlite_type: str) -> str:
    """Migration helper."""
    t = sqlite_type.upper()
    if "INT" in t:
        return "BIGINT"
    if "REAL" in t or "FLOA" in t or "DOUB" in t:
        return "DOUBLE"
    if "BOOL" in t:
        return "BOOLEAN"
    if "BLOB" in t:
        return "STRING"
    if "DATE" in t and "TIME" not in t:
        return "DATE"
    if "TIME" in t:
        return "DATETIME"
    return "VARCHAR(65535)"


def clean_val(val, col_type="VARCHAR"):
    """Migration helper."""
    if val is None:
        return None
    if isinstance(val, bytes):
        try:
            val = val.decode('utf-8', 'ignore')
        except:
            return None
    if isinstance(val, str):
        val = val.replace('\x00', '')
        return val
    return val


def migrate_db(db_name: str):
    """Migration helper."""
    print(f"\n{'='*60}")
    print(f"[INFO] Processing database: {db_name}")
    print(f"{'='*60}")

    sqlite_file = os.path.join(SQLITE_ROOT, db_name, f"{db_name}.sqlite")
    if not os.path.exists(sqlite_file):
        print("[INFO] Operation status updated.")
        return

    sqlite_conn = sqlite3.connect(sqlite_file)
    sqlite_cur = sqlite_conn.cursor()

    sr_conn = get_sr_connection()
    sr_cur = sr_conn.cursor()

    safe_db = safe_name(db_name)
    try:
        sr_cur.execute(f"DROP DATABASE IF EXISTS {safe_db}")
        sr_cur.execute(f"CREATE DATABASE {safe_db}")
        sr_cur.execute(f"USE {safe_db}")
        print(f"[ERROR] {e}")
    except Exception as e:
        print(f"[ERROR] {e}")
        sqlite_conn.close()
        sr_conn.close()
        return

    sqlite_cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [t[0] for t in sqlite_cur.fetchall() if not t[0].startswith("sqlite_")]

    for table in tables:
        print(f"[INFO] Processing table: {table}")

        sqlite_cur.execute(f'PRAGMA table_info("{table}")')
        cols = sqlite_cur.fetchall()

        col_defs = []
        col_names = []
        col_types = []

        for _, col_name, col_type, *_ in cols:
            safe_col = safe_name(col_name)
            sr_type = map_type(col_type)
            col_defs.append(f"{safe_col} {sr_type}")
            col_names.append(safe_col)
            col_types.append(sr_type)

        distribution_col = col_names[0] if col_names else "`col_1`"

        for col_name in col_names:
            col_lower = col_name.lower().replace('`', '')
            if 'id' in col_lower or 'uuid' in col_lower:
                distribution_col = col_name
                break
        else:
            try:
                sqlite_cur.execute(f'SELECT * FROM "{table}" LIMIT 1000')
                sample_rows = sqlite_cur.fetchall()
                if sample_rows:
                    for col_idx, col_name in enumerate(col_names):
                        non_null_count = sum(1 for row in sample_rows if row[col_idx] is not None)
                        null_ratio = 1.0 - (non_null_count / len(sample_rows))
                        if null_ratio == 0:
                            distribution_col = col_name
                            break
            except:
                pass

        safe_table = safe_name(table)
        try:
            sr_cur.execute(f"DROP TABLE IF EXISTS {safe_table}")
        except:
            pass

        create_sql = f"""
            CREATE TABLE {safe_table} (
                {', '.join(col_defs)}
            )
            DUPLICATE KEY ({distribution_col})
            DISTRIBUTED BY HASH({distribution_col}) BUCKETS 10
            PROPERTIES ("replication_num" = "1")
        """

        try:
            sr_cur.execute(create_sql)
        except Exception as e:
            print(f"[ERROR] {e}")
            print(f"    [SQL] {create_sql[:300]}...")
            continue

        sqlite_cur.execute(f'SELECT * FROM "{table}"')
        rows = sqlite_cur.fetchall()

        if not rows:
            print("[INFO] Operation status updated.")
            continue

        total_rows = len(rows)

        dist_col_clean = distribution_col.replace('`', '')
        distribution_col_idx = -1
        for idx, col_name in enumerate(col_names):
            if col_name.replace('`', '') == dist_col_clean:
                distribution_col_idx = idx
                break
        if distribution_col_idx == -1:
            distribution_col_idx = 0

        null_count = sum(1 for row in rows if row[distribution_col_idx] is None)
        success_cnt = 0
        error_cnt = 0

        print("[INFO] Operation status updated.")

        placeholders = ", ".join(["%s"] * len(col_names))
        insert_sql = "INSERT INTO {} ({}) VALUES ({})".format(
            safe_table,
            ', '.join(col_names),
            placeholders
        )

        for i in range(0, total_rows, BATCH_SIZE):
            batch = rows[i:i + BATCH_SIZE]

            cleaned_batch = []
            for row in batch:
                cleaned_row = []
                for idx, v in enumerate(row):
                    if idx == distribution_col_idx and v is None:
                        col_type = col_types[idx]
                        if "INT" in col_type or "BIGINT" in col_type or "DOUBLE" in col_type:
                            cleaned_row.append(0)
                        else:
                            cleaned_row.append("__NULL__")
                    else:
                        cleaned_row.append(clean_val(v, col_types[idx]))
                cleaned_batch.append(tuple(cleaned_row))

            try:
                sr_cur.executemany(insert_sql, cleaned_batch)
                success_cnt += len(cleaned_batch)
            except Exception as e:
                print(f"[ERROR] {e}")
                for batch_idx, cleaned_row in enumerate(cleaned_batch):
                    try:
                        sr_cur.execute(insert_sql, cleaned_row)
                        success_cnt += 1
                    except Exception as row_err:
                        error_cnt += 1
                        if error_cnt <= 5:
                            print(f"[ERROR] {e}")
                            print(f"[ERROR] {e}")
                            print("[INFO] Operation status updated.")

                            print("[INFO] Operation status updated.")
                            for col_idx, (col_name, val) in enumerate(zip(col_names, cleaned_row)):
                                val_len = len(str(val)) if val is not None else 0
                                val_type = type(val).__name__
                                print(f"[ERROR] {e}")

                            print("[INFO] Operation status updated.")
                            print(f"[ERROR] {e}")
                            if error_cnt == 5:
                                print("[INFO] Operation status updated.")
                    if error_cnt >= 10:
                        break

            if (i + BATCH_SIZE) % (BATCH_SIZE * 5) == 0 or i + BATCH_SIZE >= total_rows:
                print("[INFO] Operation status updated.")

        print(f"[ERROR] {e}")

    sqlite_conn.close()
    sr_conn.close()
    print(f"[INFO] Processing database: {db_name}")


def main():
    """Migration helper."""
    print("[INFO] Operation status updated.")
    print("="*60)

    try:
        conn = get_sr_connection()
        print("[INFO] Operation status updated.")
        conn.close()
    except Exception as e:
        print(f"[ERROR] {e}")
        return

    for db in DATABASES:
        try:
            migrate_db(db)
        except Exception as e:
            print(f"[ERROR] {e}")
            import traceback
            traceback.print_exc()
            continue

    print(f"\n{'='*60}")
    print("[INFO] Operation status updated.")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
