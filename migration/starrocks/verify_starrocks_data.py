"""
==========================
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
# =================================================


def safe_name(name: str) -> str:
    """
    """
    clean = re.sub(r'[^a-zA-Z0-9_]', '_', name)
    clean = re.sub(r'_+', '_', clean).strip('_')
    if not clean:
        clean = "col_unknown"
    if clean[0].isdigit():
        clean = "col_" + clean
    return f"`{clean}`"


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


def get_sqlite_row_counts(db_path):
    """Migration helper."""
    counts = {}
    if not os.path.exists(db_path):
        return None

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [t[0] for t in cursor.fetchall() if not t[0].startswith("sqlite_")]

    for table in tables:
        try:
            cursor.execute(f'SELECT COUNT(*) FROM "{table}"')
            counts[table] = cursor.fetchone()[0]
        except Exception:
            counts[table] = -1

    conn.close()
    return counts


def get_starrocks_count(db_name: str, table_name: str):
    """Migration helper."""
    try:
        conn = get_sr_connection()
        cursor = conn.cursor()

        sr_db = safe_name(db_name)
        sr_table = safe_name(table_name)

        cursor.execute(f'SELECT COUNT(*) FROM {sr_db}.{sr_table}')
        count = cursor.fetchone()[0]
        conn.close()
        return count

    except Exception as e:
        return f"Error: {str(e)[:60]}"


def main():
    """Migration helper."""
    print("=" * 100)
    print("[INFO] Operation status updated.")
    print("=" * 100)

    try:
        conn = get_sr_connection()
        print("[INFO] Operation status updated.")
        conn.close()
    except Exception as e:
        print(f"[ERROR] {e}")
        return

    total_tables = 0
    mismatch_count = 0
    ok_count = 0

    for db_name in DATABASES:
        sqlite_file = os.path.join(SQLITE_ROOT, db_name, f"{db_name}.sqlite")
        sqlite_counts = get_sqlite_row_counts(sqlite_file)

        if sqlite_counts is None:
            print(f"[INFO] Processing database: {db_name}")
            print("-" * 100)
            continue

        for table, sqlite_cnt in sqlite_counts.items():
            total_tables += 1
            sr_cnt = get_starrocks_count(db_name, table)

            if isinstance(sr_cnt, int):
                if sqlite_cnt == sr_cnt:
                    status = "OK"
                    ok_count += 1
                else:
                    diff = sr_cnt - sqlite_cnt
                    diff_pct = (diff / sqlite_cnt * 100) if sqlite_cnt > 0 else 0
                    if abs(diff_pct) < 1:
                        status = "OK"
                        ok_count += 1
                    else:
                        status = "OK"
                        mismatch_count += 1
            else:
                status = "OK"
                mismatch_count += 1

            print(f"{db_name:<25} | {table:<35} | {sqlite_cnt:<10} | {sr_display:<10} | {status}")

            if isinstance(sr_cnt, str):
                print(f"{'':<25} |   -> {sr_cnt}")

        print("-" * 100)

    print(f"[INFO] Total tables checked: {total_tables}")
    if mismatch_count == 0:
        print("[INFO] Operation status updated.")
    else:
        print(f"[ERROR] Mismatched tables: {mismatch_count}")


if __name__ == "__main__":
    main()
