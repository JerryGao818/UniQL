import csv
import json
import os
import re
import sqlite3
from pathlib import Path


RESERVED_KEYWORDS = {
    "order",
    "group",
    "user",
    "date",
    "timestamp",
    "interval",
    "from",
    "to",
    "select",
    "table",
}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def bird_root() -> Path:
    env_root = os.getenv("BIRD_DEV_ROOT")
    if env_root:
        return Path(env_root).resolve()
    return Path(os.getenv("UNIQL_BIRD_DEV_ROOT", "<BIRD_DEV_ROOT>")).resolve()


def sqlite_db_root() -> Path:
    env_root = os.getenv("DB_ROOT_DIR")
    if env_root:
        return Path(env_root).resolve()
    return (bird_root() / "dev_databases").resolve()


def clean_identifier(name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_]", "_", str(name)).lower()
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    if not cleaned:
        cleaned = "col_unknown"
    if cleaned[0].isdigit():
        cleaned = f"col_{cleaned}"
    if cleaned in RESERVED_KEYWORDS:
        cleaned = f"{cleaned}_col"
    return cleaned


def quote_sqlite_identifier(name: str) -> str:
    escaped = str(name).replace('"', '""')
    return '"' + escaped + '"'


def list_bird_databases(root: Path | None = None) -> list[str]:
    db_root = Path(root) if root else sqlite_db_root()
    dbs = []
    for entry in db_root.iterdir():
        if not entry.is_dir():
            continue
        sqlite_file = entry / f"{entry.name}.sqlite"
        if sqlite_file.exists():
            dbs.append(entry.name)
    return sorted(dbs)


def sqlite_path(db_id: str, root: Path | None = None) -> Path:
    db_root = Path(root) if root else sqlite_db_root()
    return db_root / db_id / f"{db_id}.sqlite"


def get_tables(sqlite_file: str | Path) -> list[str]:
    conn = sqlite3.connect(str(sqlite_file))
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        return [row[0] for row in cursor.fetchall() if not row[0].startswith("sqlite_")]
    finally:
        conn.close()


def get_columns(sqlite_file: str | Path, table_name: str) -> list[dict]:
    conn = sqlite3.connect(str(sqlite_file))
    try:
        cursor = conn.cursor()
        cursor.execute(f"PRAGMA table_info({quote_sqlite_identifier(table_name)})")
        columns = []
        for _, column_name, declared_type, *_ in cursor.fetchall():
            columns.append(
                {
                    "original_name": column_name,
                    "clean_name": clean_identifier(column_name),
                    "declared_type": declared_type or "",
                }
            )
        return columns
    finally:
        conn.close()


def fetch_all_rows(sqlite_file: str | Path, table_name: str) -> list[tuple]:
    conn = sqlite3.connect(str(sqlite_file))
    try:
        cursor = conn.cursor()
        cursor.execute(f"SELECT * FROM {quote_sqlite_identifier(table_name)}")
        return cursor.fetchall()
    finally:
        conn.close()


def iter_rows(sqlite_file: str | Path, table_name: str, batch_size: int = 1000):
    conn = sqlite3.connect(str(sqlite_file))
    try:
        cursor = conn.cursor()
        cursor.execute(f"SELECT * FROM {quote_sqlite_identifier(table_name)}")
        while True:
            rows = cursor.fetchmany(batch_size)
            if not rows:
                break
            yield rows
    finally:
        conn.close()


def infer_declared_kind(declared_type: str) -> str:
    dtype = (declared_type or "").upper()
    if "INT" in dtype:
        return "int"
    if "REAL" in dtype or "FLOA" in dtype or "DOUB" in dtype or "NUM" in dtype or "DEC" in dtype:
        return "float"
    if "BOOL" in dtype:
        return "bool"
    return "text"


def clean_cell_for_tsv(value):
    if value is None:
        return r"\N"
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="ignore")
    text = str(value)
    text = text.replace("\\", "\\\\")
    text = text.replace("\t", " ")
    text = text.replace("\n", " ").replace("\r", "")
    return text.strip()


def map_sqlite_to_hive_type(declared_type: str) -> str:
    kind = infer_declared_kind(declared_type)
    if kind == "int":
        return "INT"
    if kind == "float":
        return "DOUBLE"
    if kind == "bool":
        return "BOOLEAN"
    return "STRING"


def map_sqlite_to_trino_type(declared_type: str) -> str:
    kind = infer_declared_kind(declared_type)
    if kind == "int":
        return "INTEGER"
    if kind == "float":
        return "DOUBLE"
    if kind == "bool":
        return "BOOLEAN"
    return "VARCHAR"


def max_text_lengths(sqlite_file: str | Path, table_name: str, columns: list[dict]) -> dict[str, int]:
    conn = sqlite3.connect(str(sqlite_file))
    try:
        cursor = conn.cursor()
        lengths = {}
        for column in columns:
            if infer_declared_kind(column["declared_type"]) != "text":
                continue
            sql = f"SELECT MAX(LENGTH(CAST({quote_sqlite_identifier(column['original_name'])} AS TEXT))) FROM {quote_sqlite_identifier(table_name)}"
            cursor.execute(sql)
            value = cursor.fetchone()[0]
            lengths[column["original_name"]] = int(value or 0)
        return lengths
    finally:
        conn.close()


def normalize_for_doris(value, declared_type: str):
    if value is None:
        return None
    kind = infer_declared_kind(declared_type)
    try:
        if kind == "int":
            return int(value)
        if kind == "float":
            return float(value)
        if kind == "bool":
            if isinstance(value, str):
                return 1 if value.strip().lower() in {"1", "true", "t", "yes"} else 0
            return 1 if value else 0
    except Exception:
        return str(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="ignore")
    return str(value)


def map_sqlite_to_doris_type(declared_type: str, text_length: int = 0, key_column: bool = False) -> str:
    kind = infer_declared_kind(declared_type)
    if kind == "int":
        return "BIGINT"
    if kind == "float":
        return "DOUBLE"
    if kind == "bool":
        return "BOOLEAN"
    if key_column:
        varchar_len = max(1, min(text_length or 32, 1024))
        return f"VARCHAR({varchar_len})"
    return "STRING"


def parquet_arrow_type(declared_type: str):
    import pyarrow as pa

    kind = infer_declared_kind(declared_type)
    if kind == "int":
        return pa.int64()
    if kind == "float":
        return pa.float64()
    if kind == "bool":
        return pa.bool_()
    return pa.string()


def normalize_for_parquet(value, declared_type: str):
    if value is None:
        return None
    kind = infer_declared_kind(declared_type)
    try:
        if kind == "int":
            return int(value)
        if kind == "float":
            return float(value)
        if kind == "bool":
            if isinstance(value, str):
                return value.strip().lower() in {"1", "true", "t", "yes"}
            return bool(value)
    except Exception:
        return str(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="ignore")
    return str(value)


def export_table_to_parquet(sqlite_file: str | Path, table_name: str, output_file: str | Path, columns: list[dict]):
    import pyarrow as pa
    import pyarrow.parquet as pq

    rows = fetch_all_rows(sqlite_file, table_name)
    arrays = []
    for index, column in enumerate(columns):
        arrow_type = parquet_arrow_type(column["declared_type"])
        values = [normalize_for_parquet(row[index], column["declared_type"]) for row in rows]
        arrays.append(pa.array(values, type=arrow_type))

    table = pa.Table.from_arrays(arrays, names=[column["clean_name"] for column in columns])
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, output_path)


def write_name_map(output_path: str | Path, payload: dict):
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)


def write_tsv(rows: list[tuple], output_file: str | Path):
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n", quoting=csv.QUOTE_NONE, escapechar="\\")
        for row in rows:
            writer.writerow([clean_cell_for_tsv(value) for value in row])
