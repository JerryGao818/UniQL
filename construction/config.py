import os


# Database configurations. Override these values with environment variables
# before running the construction pipeline in a local database environment.
MYSQL_CONFIG = {
    "host": os.getenv("UNIQL_MYSQL_HOST", "localhost"),
    "user": os.getenv("UNIQL_MYSQL_USER", "root"),
    "password": os.getenv("UNIQL_MYSQL_PASSWORD", ""),
    "charset": "utf8mb4",
}

MSSQL_CONFIG = {
    "server": os.getenv("UNIQL_MSSQL_SERVER", "localhost"),
    "user": os.getenv("UNIQL_MSSQL_USER", "SA"),
    "password": os.getenv("UNIQL_MSSQL_PASSWORD", ""),
    "charset": "utf8",
}

PG_CONFIG = {
    "host": os.getenv("UNIQL_PG_HOST", "localhost"),
    "port": os.getenv("UNIQL_PG_PORT", "5432"),
    "user": os.getenv("UNIQL_PG_USER", "postgres"),
    "password": os.getenv("UNIQL_PG_PASSWORD", ""),
}

ORACLE_DSN = os.getenv("UNIQL_ORACLE_DSN", "localhost:1521/XE")
ORACLE_USER_PREFIX = os.getenv("UNIQL_ORACLE_USER_PREFIX", "")
ORACLE_PASSWORD = os.getenv("UNIQL_ORACLE_PASSWORD", "")

HIVE_CONFIG = {
    "docker_container": os.getenv("UNIQL_HIVE_CONTAINER", "hive-server"),
}

# Paths
INPUT_DATA_PATH = os.getenv("UNIQL_INPUT_DATA_PATH", "../../Bird_dataset/dev/dev.json")
DB_ROOT_DIR = os.getenv("UNIQL_DB_ROOT_DIR", "../../Bird_dataset/dev/dev_databases")
DATE_LOG_DIR = os.getenv("UNIQL_LOG_DIR", "./logs")
RULES_DIR = os.getenv("UNIQL_RULES_DIR", "./rules")

# Azure OpenAI-compatible translator backend.
AZURE_OPENAI_CONFIG = {
    "api_key": os.getenv("AZURE_OPENAI_API_KEY", ""),
    "azure_endpoint": os.getenv("AZURE_OPENAI_ENDPOINT", ""),
    "api_version": os.getenv("AZURE_OPENAI_API_VERSION", "2025-04-01-preview"),
}

# Optimizer LLM backend used for rule refinement.
OPTIMIZER_CONFIG = {
    "url": os.getenv("UNIQL_OPTIMIZER_URL", ""),
    "api_key": os.getenv("UNIQL_OPTIMIZER_API_KEY", ""),
    "model": os.getenv("UNIQL_OPTIMIZER_MODEL", "gemini-2.5-pro"),
}
