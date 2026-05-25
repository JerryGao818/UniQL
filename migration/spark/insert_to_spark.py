"""
Migration helper.
==========================================
Migration helper.
Migration helper.
Migration helper.
Migration helper.
"""

import sqlite3
import os
import re
from datetime import datetime, date

from pyspark.sql import SparkSession
from pyspark.sql.types import (
    StructType, StructField,
    StringType, LongType, DoubleType,
    BooleanType, TimestampType, BinaryType
)

BIRD_ROOT = '/data/Bird_dataset/dev/dev_databases/dev_databases/'

DATABASES = [
    'california_schools', 'card_games', 'european_football_2',
    'formula_1', 'student_club', 'thrombosis_prediction',
    'toxicology', 'superhero', 'codebase_community',
    'debit_card_specializing', 'financial'
]
# ===========================================


def clean_name(name: str) -> str:
    """
    Migration helper.
    Migration helper.
    Migration helper.
    Migration helper.
    Migration helper.
    """
    clean = re.sub(r'[^a-zA-Z0-9_]', '_', name)
    clean = re.sub(r'_+', '_', clean)
    clean = clean.strip('_')
    if not clean: clean = "col_unknown"
    if clean[0].isdigit():
        clean = "col_" + clean
    return clean


def map_sqlite_type(sqlite_type: str):
    """
    Migration helper.
    Migration helper.
    """
    t = sqlite_type.upper()

    if 'INT' in t:
        return DoubleType()
    if 'REAL' in t or 'FLOA' in t or 'DOUB' in t:
        return DoubleType()
    if 'BOOL' in t:
        return BooleanType()
    if 'DATE' in t or 'TIME' in t:
        return TimestampType()
    if 'BLOB' in t:
        return BinaryType()

    return StringType()


def clean_value_for_spark(value, spark_type):
    """
    Migration helper.
    Migration helper.
    """
    if value is None:
        return None

    if isinstance(spark_type, TimestampType):
        if isinstance(value, str):
            value = value.strip()
            time_formats = [
                "%Y-%m-%d",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M:%S.%f",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%dT%H:%M:%S.%f",
            ]
            for fmt in time_formats:
                try:
                    return datetime.strptime(value, fmt)
                except ValueError:
                    pass
            return None
        if isinstance(value, date):
            return datetime.combine(value, datetime.min.time())

    if isinstance(spark_type, DoubleType):
        return float(value)

    return value


def main():
    spark = (
        SparkSession.builder
        .appName("SQLite-to-Spark")
        .enableHiveSupport()
        .config("spark.sql.warehouse.dir", "/workspace/spark-warehouse")
        .getOrCreate()
    )

    spark.sparkContext.setLogLevel("ERROR")

    import logging
    logging.getLogger("py4j").setLevel(logging.ERROR)

    for db_name in DATABASES:
        sqlite_file = os.path.join(BIRD_ROOT, db_name, f"{db_name}.sqlite")
        if not os.path.exists(sqlite_file):
            print(f"[SKIP] File not found: {sqlite_file}")
            continue

        spark_db = clean_name(db_name)
        print(f"[ERROR] Migration failed: {db}")

        spark.sql(f"CREATE DATABASE IF NOT EXISTS {spark_db}")
        spark.sql(f"USE {spark_db}")

        sqlite_conn = sqlite3.connect(sqlite_file)
        cursor = sqlite_conn.cursor()

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cursor.fetchall()]

        for table in tables:
            if table.startswith("sqlite_"):
                continue

            print(f"[INFO] Processing table: {table}")

            cursor.execute(f'PRAGMA table_info("{table}")')
            cols = cursor.fetchall()

            fields = []
            col_names = []

            for col in cols:
                raw_name = col[1]
                raw_type = col[2]

                clean_col = clean_name(raw_name)
                spark_type = map_sqlite_type(raw_type)

                fields.append(
                    StructField(clean_col, spark_type, True)
                )
                col_names.append(clean_col)

            schema = StructType(fields)

            cursor.execute(f'SELECT * FROM "{table}"')
            rows = cursor.fetchall()

            cleaned_rows = []
            for row in rows:
                cleaned_row = [
                    clean_value_for_spark(v, field.dataType)
                    for v, field in zip(row, schema.fields)
                ]
                cleaned_rows.append(tuple(cleaned_row))

            df = spark.createDataFrame(
                cleaned_rows,
                schema=schema
            )

            spark_table = clean_name(table)
            (
                df.write
                .mode("overwrite")
                .format("parquet")
                .saveAsTable(spark_table)
            )

        sqlite_conn.close()

    spark.stop()
    print("[INFO] Operation status updated.")


if __name__ == "__main__":
    main()
