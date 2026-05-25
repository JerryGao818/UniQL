import os
import sqlite3
import re

from pyspark.sql import SparkSession


BIRD_ROOT = "/data/Bird_dataset/dev/dev_databases/dev_databases/"

DATABASES = [
    'superhero', 'codebase_community', 'debit_card_specializing',
    'financial', 'california_schools', 'card_games',
    'european_football_2', 'formula_1', 'student_club',
    'thrombosis_prediction', 'toxicology'
]

# ============================================


def clean_name(name: str) -> str:
    """
    Migration helper.
    Migration helper.
    """
    clean = re.sub(r'[^a-zA-Z0-9_]', '_', name)
    clean = re.sub(r'_+', '_', clean).strip('_')
    if not clean:
        clean = "col_unknown"
    if clean[0].isdigit():
        clean = f"col_{clean}"
    return clean


def get_sqlite_row_counts(sqlite_file):
    """
    Migration helper.
    { table_name -> row_count }
    """
    if not os.path.exists(sqlite_file):
        return None

    conn = sqlite3.connect(sqlite_file)
    cursor = conn.cursor()

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cursor.fetchall()]

    counts = {}
    for table in tables:
        if table.startswith("sqlite_"):
            continue
        try:
            cursor.execute(f'SELECT COUNT(*) FROM "{table}"')
            counts[table] = cursor.fetchone()[0]
        except Exception:
            counts[table] = -1

    conn.close()
    return counts


def get_spark_table_count(spark, db_name, table_name):
    """
    Migration helper.
    """
    try:
        spark.sql(f"USE {db_name}")
        result = spark.sql(f"SELECT COUNT(*) FROM {table_name}")
        return result.collect()[0][0]
    except Exception as e:
        return f"Error: {str(e)}"


def main():
    spark = (
        SparkSession.builder
        .appName("Verify-SQLite-vs-Spark")
        .enableHiveSupport()
        .getOrCreate()
    )

    spark.sparkContext.setLogLevel("ERROR")
    import logging
    logging.getLogger("py4j").setLevel(logging.ERROR)

    header = f"{'Database':<25} | {'Table':<35} | {'SQLite':<10} | {'Spark':<10} | {'Status'}"
    print("=" * 105)
    print(header)
    print("=" * 105)

    total_tables = 0
    mismatch_count = 0

    for db in DATABASES:
        sqlite_file = os.path.join(BIRD_ROOT, db, f"{db}.sqlite")
        sqlite_counts = get_sqlite_row_counts(sqlite_file)

        if sqlite_counts is None:
            print(f"[ERROR] {e}")
            continue

        spark_db = clean_name(db)

        for table, sqlite_cnt in sqlite_counts.items():
            total_tables += 1

            spark_table = clean_name(table)
            spark_cnt = get_spark_table_count(spark, spark_db, spark_table)

            if isinstance(spark_cnt, int):
                if sqlite_cnt == spark_cnt:
                    status = "OK"
                else:
                    status = "MISMATCH"
                    mismatch_count += 1
            else:
                status = "SPARK ERR"
                mismatch_count += 1

            spark_display = str(spark_cnt)
            if len(spark_display) > 10:
                spark_display = "Error..."

            print(
                f"{db:<25} | {table:<35} | "
                f"{str(sqlite_cnt):<10} | {spark_display:<10} | {status}"
            )

            if "Error" in str(spark_cnt):
                print(f"{'':<25} |   -> {spark_cnt}")

        print("-" * 105)

    print("[INFO] Operation status updated.")
    print(f"[INFO] Total tables checked: {total_tables}")
    if mismatch_count == 0:
        print("[INFO] Operation status updated.")
    else:
        print(f"[ERROR] Mismatched tables: {mismatch_count}")

    spark.stop()


if __name__ == "__main__":
    main()
