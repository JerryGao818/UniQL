import argparse
import json
import os
import re
from pathlib import Path

SUPPORTED_DIALECTS = [
    "clickhouse",
    "doris",
    "drill",
    "druid",
    "duckdb",
    "hive",
    "mysql",
    "oracle",
    "postgresql",
    "presto",
    "spark",
    "starrocks",
    "sqlite",
    "mssql",
    "teradata",
    "trino",
]

DIALECT_ALIASES = {
    "postgre": "postgresql",
    "sqlserver": "mssql",
}


class SQLTestCase:
    question_id: int
    db_id: str
    question: str
    evidence: str
    difficulty: str
    dialect: str
    ground_truth_sql:str
    annotation_source:str
    schema_str: str 
def load_questions(input_file):
    questions = json.load(open(input_file, 'r', encoding='utf-8'))
    return questions


def normalize_dialect(dialect):
    if dialect == "all":
        return dialect
    dialect = dialect.lower()
    if dialect in SUPPORTED_DIALECTS:
        return dialect
    if dialect in DIALECT_ALIASES:
        return DIALECT_ALIASES[dialect]
    raise ValueError(f"Unsupported dialect: {dialect}")


def sql_field_to_dialect(field):
    field = field.lower()
    if not field.startswith("sql-"):
        return None
    try:
        return normalize_dialect(field[len("sql-"):])
    except ValueError:
        return None


def get_available_dialects(data):
    dialects = []
    for key in data:
        dialect = sql_field_to_dialect(key)
        if dialect and dialect not in dialects:
            dialects.append(dialect)
    return dialects


def get_ground_truth_sql(data, dialect):
    expected_field = f"sql-{dialect}"
    for key, value in data.items():
        if key.lower() == expected_field:
            return value
    return ""


def load_schema_for_dialect(schema_path, dialect, db_id):
    schema_file = Path(schema_path) / f"{dialect}_schema.json"
    return json.load(open(schema_file, 'r', encoding='utf-8'))[db_id]


def resolve_schema_str(data, schema_path, dialect):
    return load_schema_for_dialect(schema_path, dialect, data["db_id"])


def buildTestCases(questions, schema_path, target_dialect="all"):
    test_cases = []
    for data in questions:
        available_dialects = get_available_dialects(data)
        if target_dialect == "all":
            dialects = available_dialects
        else:
            dialects = [target_dialect]
        for dialect in dialects:
            test_case = SQLTestCase()
            test_case.question_id = data["question_id"]
            test_case.db_id = data["db_id"]
            test_case.question = data["question"]
            test_case.evidence = data.get("evidence", "")
            test_case.difficulty = data["difficulty"]
            test_case.annotation_source = data.get("annotation_source", "glot")
            test_case.dialect = dialect
            test_case.ground_truth_sql = get_ground_truth_sql(data, dialect)
            test_case.schema_str = resolve_schema_str(data, schema_path, dialect)
            test_cases.append(test_case)
    return test_cases


def prompt_format(test_cases:list, prompt_path):
    prompts_by_dialect = {dialect: [] for dialect in SUPPORTED_DIALECTS}
    prompt_template = open(prompt_path, 'r', encoding='utf-8').read()
    for case in test_cases:
        evidence = f"Evidence:\n{case.evidence}" if case.evidence else ""
        prompt_item = {
            "question_id": case.question_id,
            "prompt": None,
            "question": case.question,
            "evidence": case.evidence,
            "difficulty": case.difficulty,
            "db_id": case.db_id,
            "ground_truth_sql": case.ground_truth_sql,
            "annotation_source": case.annotation_source,
            "dialect": case.dialect,
        }
        prompt = prompt_template.format(
            dialect=case.dialect,
            db_details=case.schema_str,
            evidence=evidence,
            question=case.question
        )
        prompt_item["prompt"] = prompt
        prompts_by_dialect[case.dialect].append(prompt_item)

    return prompts_by_dialect

def parse_response(response):
    pattern = r"```sql\s*(.*value)\s*```"
    
    sql_blocks = re.findall(pattern, response, re.DOTALL)

    if sql_blocks:
        # Extract the last SQL query in the response text and remove extra whitespace characters
        last_sql = sql_blocks[-1].strip()
        return last_sql
    else:
        # print("No SQL blocks found.")
        return ""


def build_results(prompt_items, outputs):
    results = []
    pred_sql = []
    for data, output in zip(prompt_items, outputs):
        responses = [o.text for o in output.outputs]
        sqls = [parse_response(r) for r in responses]

        result_item = {
            "question_id": data["question_id"],
            "db_id": data["db_id"],
            "question": data["question"],
            "difficulty": data["difficulty"],
            "ground_truth_sql": data["ground_truth_sql"],
            "prompt": data["prompt"],
            "responses": responses,
            "pred_sqls": sqls,
        }
        pred_item = {
            "question_id": data["question_id"],
            "db_id": data["db_id"],
            "pred_sqls": sqls,
            "ground_truth_sql": data["ground_truth_sql"],
            "difficulty": data["difficulty"],
        }
        if data.get("annotation_source"):
            result_item["annotation_source"] = data["annotation_source"]
            pred_item["annotation_source"] = data["annotation_source"]
        results.append(result_item)
        pred_sql.append(pred_item)
    return results, pred_sql

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    project_dir = Path(__file__).resolve().parent
    parser.add_argument("--model", type=str, default=None, help="model name under UNIQL_MODEL_ROOT")
    parser.add_argument("--pretrained_model_name_or_path", type = str, default = None)
    parser.add_argument("--input_file", type = str, default=str(project_dir / "data" / "hive.json"))
    parser.add_argument("--output_file", type = str, default=str(project_dir / "results-human"))
    parser.add_argument("--tensor_parallel_size", type = int, help = "the number of used GPUs", default = 4)
    parser.add_argument("--n", type = int, help = "the number of generated responses", default = 1)
    parser.add_argument("--temperature", type = float, help = "temperature of llm's sampling", default = 0)
    parser.add_argument("--schema_dir", type = str, help = "the directory of database schemas", default = str(project_dir / "schema"))
    parser.add_argument("--dialect", type=str, default="all", help="target SQL dialect to generate")
    parser.add_argument("--max_model_len", type=int, default=8192, help="maximum model context length")
    parser.add_argument("--max_input_len", type=int, default=2048, help="reserved input context length")
    parser.add_argument("--max_output_len", type=int, default=6144, help="maximum generation length")
    parser.add_argument("--dry_run", action="store_true", help="validate prompt building and file paths without loading the model")
    prompt_template_path = project_dir / "template.txt"
    opt = parser.parse_args()
    opt.dialect = normalize_dialect(opt.dialect)
    if opt.model:
        opt.pretrained_model_name_or_path = str(Path(os.getenv('UNIQL_MODEL_ROOT', '<MODEL_ROOT>')) / opt.model)
        opt.output_file = str(Path(opt.output_file) / opt.model)
    elif not opt.pretrained_model_name_or_path:
        opt.pretrained_model_name_or_path = str(Path(os.getenv('UNIQL_MODEL_ROOT', '<MODEL_ROOT>')) / 'Qwen3-8B')
    print(opt)
    
    questions = load_questions(opt.input_file)
    test_cases = buildTestCases(questions, opt.schema_dir, opt.dialect)
    prompts_by_dialect = prompt_format(test_cases, prompt_template_path)
    output_dir = Path(opt.output_file)
    output_dir.mkdir(parents=True, exist_ok=True)

    if opt.dry_run:
        print("Dry run completed successfully.")
        print(f"Loaded {len(questions)} questions and built {len(test_cases)} test cases.")
        print("Prompt counts:", {dialect: len(items) for dialect, items in prompts_by_dialect.items() if items})
        first_available = next((items for items in prompts_by_dialect.values() if items), None)
        if first_available:
            print("Sample prompt preview:")
            print(first_available[0]["prompt"][:1000])
        raise SystemExit(0)

    # input_dataset = json.load(open(opt.input_file))
    from transformers import AutoTokenizer
    from vllm import LLM, SamplingParams

    tokenizer = AutoTokenizer.from_pretrained(opt.pretrained_model_name_or_path, trust_remote_code=True)
    
    if "Qwen2.5-" in opt.pretrained_model_name_or_path:
        stop_token_ids = [151645] # 151645 is the token id of <|im_end|> (end of turn token in Qwen2.5)
    elif "deepseek-coder-" in opt.pretrained_model_name_or_path:
        stop_token_ids = [32021]
    elif "DeepSeek-Coder-V2" in opt.pretrained_model_name_or_path:
        stop_token_ids = [100001]
    elif "OpenCoder-" in opt.pretrained_model_name_or_path:
        stop_token_ids = [96539]
    elif "Meta-Llama-" in opt.pretrained_model_name_or_path:
        stop_token_ids = [128009, 128001]
    elif "granite-" in opt.pretrained_model_name_or_path:
        stop_token_ids = [0] # <|end_of_text|> is the end token of granite-3.1 and granite-code
    elif "starcoder2-" in opt.pretrained_model_name_or_path:
        stop_token_ids = [0] # <|end_of_text|> is the end token of starcoder2
    elif "Codestral-" in opt.pretrained_model_name_or_path:
        stop_token_ids = [2]
    elif "Mixtral-" in opt.pretrained_model_name_or_path:
        stop_token_ids = [2]
    elif "OmniSQL-" in opt.pretrained_model_name_or_path:
        stop_token_ids = [151645] # OmniSQL uses the same tokenizer as Qwen2.5
    else:
        print("Use Qwen2.5's stop tokens by default.")
        stop_token_ids = [151645]

    print("stop_token_ids:", stop_token_ids)
    
    max_model_len = opt.max_model_len # used to allocate KV cache memory in advance
    max_input_len = opt.max_input_len
    max_output_len = opt.max_output_len # (max_input_len + max_output_len) must <= max_model_len
    if max_input_len + max_output_len > max_model_len:
        raise ValueError(
            f"Invalid length configuration: max_input_len({max_input_len}) + "
            f"max_output_len({max_output_len}) > max_model_len({max_model_len})"
        )
    
    print("max_model_len:", max_model_len)
    print("max_input_len:", max_input_len)
    print("max_output_len:", max_output_len)
    print("temperature:", opt.temperature)
    sampling_params = SamplingParams(
        temperature = opt.temperature, 
        max_tokens = max_output_len,
        n = opt.n,
        stop_token_ids = stop_token_ids
    )

    llm = LLM(
        model = opt.pretrained_model_name_or_path,
        dtype = "float16", 
        tensor_parallel_size = opt.tensor_parallel_size,
        max_model_len = max_model_len,
        gpu_memory_utilization = 0.92,
        swap_space = 0,
        enforce_eager = True,
        disable_custom_all_reduce = True,
        trust_remote_code = True
    )

    selected_dialects = [dialect for dialect, items in prompts_by_dialect.items() if items]
    if not selected_dialects:
        raise ValueError(f"No samples with golden SQL for dialect={opt.dialect} were found in {opt.input_file}.")

    for dialect in selected_dialects:
        prompt_items = prompts_by_dialect[dialect]
        print(f"Generating {dialect} SQL for {len(prompt_items)} samples...")
        chat_prompts = [tokenizer.apply_chat_template(
            [{"role": "user", "content": data["prompt"]}],
            add_generation_prompt = True, tokenize = False
        ) for data in prompt_items]
        outputs = llm.generate(chat_prompts, sampling_params)
        results, pred_sql = build_results(prompt_items, outputs)

        with open(output_dir / f"{dialect}_dev.json", "w", encoding="utf-8") as f:
            f.write(json.dumps(results, indent=2, ensure_ascii=False))
        with open(output_dir / f"{dialect}_pred_sql.json", "w", encoding="utf-8") as f:
            f.write(json.dumps(pred_sql, indent=2, ensure_ascii=False))



