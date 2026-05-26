"""
Migration helper.
===================================================
Migration helper.
Migration helper.
Migration helper.
Migration helper.
Migration helper.
Migration helper.
"""

import os
import re
import sqlite3
import teradatasql


SQLITE_ROOT = "../dev/dev_databases/dev_databases"

DATABASES = [
    'california_schools',
    'card_games',
    'european_football_2',
    'formula_1',
    'student_club',
    'thrombosis_prediction',
    'toxicology',
    'superhero',
    'codebase_community',
    'debit_card_specializing',
    'financial'
]

TD_HOST = "192.168.92.130"
TD_USER = "dbc"
TD_PASSWORD = os.getenv("UNIQL_TERADATA_PASSWORD", "<TERADATA_PASSWORD>")

# ===========================================

def safe_name(name: str) -> str:
    """
    Migration helper.
    Migration helper.
    Migration helper.
    """
    clean = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    clean = re.sub(r"_+", "_", clean).strip("_")

    if not clean:
        clean = "col_unknown"
    if clean[0].isdigit():
        clean = "col_" + clean

    return clean[:30]


def clean_string_teradata(val: str, max_bytes: int = 31000) -> str:
    if not val:
        return None

    if not isinstance(val, str):
        try:
            val = str(val)
        except:
            return None

    val = val.replace('\x00', '')

    val = re.sub(r'[\uD800-\uDFFF]', '', val)

    filtered = []
    for ch in val:
        code = ord(ch)
        if (
            32 <= code <= 126
            or 160 <= code <= 255
        ):
            filtered.append(ch)

    val = ''.join(filtered).strip()
    if not val:
        return None

    b = val.encode('latin-1', 'ignore')
    if len(b) > max_bytes:
        val = b[:max_bytes].decode('latin-1', 'ignore')

    return val


def clean_val(val):
    if val is None:
        return None
    if isinstance(val, bool):
        return int(val)
    if isinstance(val, bytes):
        try:
            val = val.decode('latin-1', 'ignore')
        except:
            return None
    if isinstance(val, str):
        return clean_string_teradata(val)
    return val


def map_type(sqlite_type: str, max_bytes: int) -> str:
    """
    Migration helper.

    Migration helper.
    Migration helper.
    Migration helper.
    """
    t = sqlite_type.upper()

    if "INT" in t:
        return "BIGINT"
    if "REAL" in t or "FLOA" in t or "DOUB" in t:
        return "FLOAT"
    if "DATE" in t and "TIME" not in t:
        return "DATE"
    if "TIME" in t:
        return "TIMESTAMP(6)"

    if max_bytes > 25000:
        return "CLOB(1000000) CHARACTER SET UNICODE"

    size = min(32000, max(500, int(max_bytes * 2.0)))
    return f"VARCHAR({size}) CHARACTER SET UNICODE"


def save_error_row(table_name: str, db_name: str, row: tuple, cols: list, error_msg: str):
    """Migration helper."""
    error_file = "error_rows.txt"

    try:
        with open(error_file, 'a', encoding='utf-8') as f:
            f.write(f"\n{'='*80}\n")
            f.write(f"Database: {db_name}\n")
            f.write(f"Table: {table_name}\n")
            f.write(f"Error: {error_msg}\n")
            f.write(f"{'='*80}\n")
            f.write(f"Columns: {cols}\n")
            f.write(f"Row values ({len(row)} columns):\n")

            for i, (col, val) in enumerate(zip(cols, row)):
                f.write(f"  [{i}] {col}: ")

                if val is None:
                    f.write("NULL\n")
                elif isinstance(val, str):
                    byte_len = len(val.encode("utf-8", errors="ignore"))
                    f.write(f"[{len(val)} chars, {byte_len} bytes]\n")

                    if len(val) <= 200:
                        f.write(f"       Value: {repr(val)}\n")
                    else:
                        f.write(f"       First 200 chars: {repr(val[:200])}\n")
                        f.write(f"       ... ({len(val)-200} more chars)\n")
                else:
                    f.write(f"{repr(val)}\n")

            f.write(f"{'='*80}\n\n")
    except Exception as e:
        print(f"[ERROR] {e}")


def fast_insert(td_cur, td_conn, td_table_name: str, col_names: list, rows: list,
                original_cols=None, table_name_raw=None, db_name=None):
    """
    Migration helper.

    Migration helper.
    Migration helper.
    Migration helper.
    Migration helper.
    Migration helper.

    Migration helper.
    """
    total = len(rows)
    if total == 0:
        return 0, 0

    cols_str = ", ".join(col_names)
    placeholders = ", ".join(["value"] * len(col_names))
    sql = f'INSERT INTO "{td_table_name}" ({cols_str}) VALUES ({placeholders})'

    success = 0
    failed = 0
    saved_errors = 0

    for batch_size in [5000, 1000, 500, 100, 1]:
        if success > 0 or failed == total:
            break

        batch_success = 0
        batch_failed = 0

        try:
            for i in range(0, total, batch_size):
                batch = rows[i:i + batch_size]

                try:
                    if batch_size == 1:
                        td_cur.execute(sql, batch[0])
                    else:
                        td_cur.executemany(sql, batch)

                    td_conn.commit()
                    batch_success += len(batch)

                    current = i + len(batch)
                    if current % (total // 10 + 1) == 0 or current == total:
                        pct = current * 100 // total
                        print("[INFO] Operation status updated.")

                except Exception as e:
                    err_msg = str(e)

                    if batch_size > 1:
                        for row_idx, row in enumerate(batch):
                            try:
                                td_cur.execute(sql, row)
                                td_conn.commit()
                                batch_success += 1
                            except Exception as e2:
                                batch_failed += 1
                                if saved_errors < 10 and original_cols:
                                    save_error_row(
                                        table_name_raw or td_table_name,
                                        db_name or "unknown",
                                        row,
                                        original_cols,
                                        str(e2)
                                    )
                                    saved_errors += 1
                                    print(f"[ERROR] {e}")

                                if batch_failed <= 3:
                                    if "6706" in str(e2):
                                        print("[INFO] Operation status updated.")
                                    else:
                                        print(f"[ERROR] {e}")
                    else:
                        batch_failed += 1

                        if saved_errors < 10 and original_cols:
                            save_error_row(
                                table_name_raw or td_table_name,
                                db_name or "unknown",
                                batch[0],
                                original_cols,
                                err_msg
                            )
                            saved_errors += 1
                            print(f"[ERROR] {e}")

                        if batch_failed <= 5:
                            if "6706" in err_msg:
                                print("[INFO] Operation status updated.")
                            else:
                                print(f"[ERROR] {e}")

            success += batch_success
            failed += batch_failed

            if batch_success > 0:
                return success, failed

        except Exception as e:
            continue

    if saved_errors > 0:
        print("[INFO] Operation status updated.")

    return success, failed


def migrate_table(sqlite_cur, td_cur, td_conn, table: str, db_name: str):
    """Migration helper."""
    print(f"[INFO] Processing table: {table}")

    sqlite_cur.execute(f'PRAGMA table_info("{table}")')
    cols = sqlite_cur.fetchall()
    col_names_raw = [c[1] for c in cols]

    sqlite_cur.execute(f'SELECT COUNT(*) FROM "{table}"')
    total_rows = sqlite_cur.fetchone()[0]

    sample_size = min(50000, total_rows)
    sqlite_cur.execute(f'SELECT * FROM "{table}" LIMIT {sample_size}')
    sample_rows = sqlite_cur.fetchall()

    max_bytes = [0] * len(cols)
    for row in sample_rows:
        for i, val in enumerate(row):
            cleaned = clean_val(val)
            if isinstance(cleaned, str):
                byte_len = len(cleaned.encode("utf-8", errors="ignore"))
                max_bytes[i] = max(max_bytes[i], byte_len)

    print("[INFO] Operation status updated.")

    td_table = safe_name(table)
    col_defs = []
    col_names = []

    for i, (_, name, ctype, *_ ) in enumerate(cols):
        td_type = map_type(ctype, max_bytes[i])
        safe_col = safe_name(name)
        col_defs.append(f'"{safe_col}" {td_type}')
        col_names.append(f'"{safe_col}"')

    try:
        td_cur.execute(f'DROP TABLE "{td_table}"')
    except:
        pass

    create_sql = f'CREATE MULTISET TABLE "{td_table}" ({", ".join(col_defs)}) PRIMARY INDEX ({col_names[0]})'
    td_cur.execute(create_sql)

    sqlite_cur.execute(f'SELECT * FROM "{table}"')
    raw_rows = sqlite_cur.fetchall()

    print("[INFO] Operation status updated.")
    rows = [tuple(clean_val(v) for v in row) for row in raw_rows]

    print("[INFO] Operation status updated.")
    success, failed = fast_insert(
        td_cur, td_conn, td_table, col_names, rows,
        original_cols=col_names_raw,
        table_name_raw=table,
        db_name=db_name
    )

    fail_pct = failed / len(rows) * 100 if rows else 0
    print("[INFO] Operation status updated.")

    return success, failed


def migrate_database(db_name: str, td_conn):
    """Migration helper."""
    print(f"\n{'='*60}")
    print(f"[INFO] Processing database: {db_name}")
    print(f"{'='*60}")

    sqlite_path = os.path.join(SQLITE_ROOT, db_name, f"{db_name}.sqlite")

    if not os.path.exists(sqlite_path):
        print("[INFO] Operation status updated.")
        return

    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_cur = sqlite_conn.cursor()
    td_cur = td_conn.cursor()

    td_db = safe_name(db_name)
    try:
        td_cur.execute(f"CREATE DATABASE {td_db} AS PERMANENT = 5e9")
    except:
        pass
    td_cur.execute(f"DATABASE {td_db}")

    sqlite_cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [t[0] for t in sqlite_cur.fetchall() if not t[0].startswith("sqlite_")]

    print("[INFO] Operation status updated.")

    total_success = 0
    total_failed = 0

    for table in tables:
        success, failed = migrate_table(sqlite_cur, td_cur, td_conn, table, db_name)
        total_success += success
        total_failed += failed

    sqlite_conn.close()

    print("[INFO] Operation status updated.")

    if total_success + total_failed > 0:
        fail_pct = total_failed / (total_success + total_failed) * 100
        print("[INFO] Operation status updated.")


def main():
    """Migration helper."""
    print("=" * 60)
    print("[INFO] Operation status updated.")
    print("=" * 60)
    print(f"Target: {TD_HOST}")
    print("[INFO] Operation status updated.")
    print("[INFO] Operation status updated.")
    print("=" * 60)

    try:
        conn = teradatasql.connect(
            host=TD_HOST,
            user=TD_USER,
            password=TD_PASSWORD,
            tmode="ANSI"
        )
        print("[INFO] Operation status updated.")
    except Exception as e:
        print(f"[ERROR] {e}")
        return

    for idx, db in enumerate(DATABASES, 1):
        print("[INFO] Operation status updated.")
        migrate_database(db, conn)

    conn.close()

    print("\n" + "=" * 60)
    print("[INFO] Operation status updated.")
    print("=" * 60)


if __name__ == "__main__":
    main()
