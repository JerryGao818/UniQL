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
    ground_truth_sql: str
    annotation_source: str
    schema_str: str


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
    return json.load(open(schema_file, "r", encoding="utf-8"))[db_id]


def load_questions(input_file):
    return json.load(open(input_file, "r", encoding="utf-8"))


def build_test_cases(questions, schema_path, target_dialect="all"):
    test_cases = []
    for data in questions:
        dialects = get_available_dialects(data) if target_dialect == "all" else [target_dialect]
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
            test_case.schema_str = load_schema_for_dialect(schema_path, dialect, data["db_id"])
            test_cases.append(test_case)
    return test_cases


def evidence_block(evidence):
    return f"Hint:\n{evidence}\n\n" if evidence else ""


def schema_linking_prompt(case):
    return f"""You are implementing the Schema Linking module from DIN-SQL in zero-shot mode.
Find the schema links needed to generate a valid {case.dialect} SQL query.

Rules:
- Use only tables and columns that appear in the schema.
- Include relevant tables, columns, join relationships that can be inferred from names, and literal values from the question or hint.
- Do not generate SQL in this step.
- Output exactly one line in this format:
Schema_links: [item1, item2, ...]

Database dialect:
{case.dialect}

Database schema:
{case.schema_str}

{evidence_block(case.evidence)}Question:
{case.question}
"""


def paper_zero_shot_prompt(case):
    return f"""Generate a valid {case.dialect} SQL query to answer the question using the given database schema.

Rules:
- Use only tables and columns from the schema.
- Follow the hint when present.
- Return exactly one SQL query prefixed by SQL:.

Database dialect:
{case.dialect}

Database schema:
{case.schema_str}

{evidence_block(case.evidence)}Question:
{case.question}

SQL:
"""


def classification_prompt(case, schema_links):
    return f"""You are implementing the Classification module from DIN-SQL in zero-shot mode.
Classify the SQL needed for the question as EASY, NON-NESTED, or NESTED.

Definitions:
- EASY: no JOIN and no nested query is needed.
- NON-NESTED: JOIN is needed, but no nested query is needed.
- NESTED: a nested query, set operation, IN/NOT IN, EXISTS, or multi-step sub-question is needed.

Output exactly:
Label: "<EASY|NON-NESTED|NESTED>"
sub_questions: [sub-question 1, ...]

Database dialect:
{case.dialect}

Database schema:
{case.schema_str}

{evidence_block(case.evidence)}Question:
{case.question}

Schema_links: {schema_links}
"""


def sql_generation_prompt(case, schema_links, label, sub_questions):
    label = label or "NESTED"
    return f"""You are implementing the SQL Generation module from DIN-SQL in zero-shot mode.
Generate the final SQL query for the given question.

Rules:
- Generate valid {case.dialect} SQL, not SQLite unless the dialect is sqlite.
- Use only tables and columns from the schema.
- Follow the hint when present.
- If the query is nested, use the sub_questions to reason, but still output one final SQL query.
- Output exactly one final SQL query prefixed by SQL:.

Database dialect:
{case.dialect}

Database schema:
{case.schema_str}

{evidence_block(case.evidence)}Question:
{case.question}

Schema_links: {schema_links}
Label: "{label}"
sub_questions: {sub_questions}

SQL:
"""


def self_correction_prompt(case, sql_query):
    return f"""You are implementing the Self-Correction module from DIN-SQL in zero-shot mode.
Check and fix the SQL query for the question.

Rules:
- Return valid {case.dialect} SQL.
- Use only tables and columns from the schema.
- Remove redundant selected columns unless the question asks for them.
- Check JOIN, WHERE, GROUP BY, ORDER BY, aggregation, NULL handling, LIMIT/OFFSET, and type casts.
- If the SQL is already correct, return it unchanged.
- Output exactly one final SQL query prefixed by Revised_SQL:.

Database dialect:
{case.dialect}

Database schema:
{case.schema_str}

{evidence_block(case.evidence)}Question:
{case.question}

SQL:
{sql_query}

Revised_SQL:
"""


def extract_schema_links(text):
    match = re.search(r"Schema_links\s*:\s*(\[.*value\])", text, re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else "[]"


def extract_label_and_sub_questions(text):
    label_match = re.search(r"Label\s*:\s*\"value(EASY|NON-NESTED|NESTED)\"value", text, re.IGNORECASE)
    label = label_match.group(1).upper() if label_match else "NESTED"
    sub_match = re.search(r"sub_questions\s*:\s*(\[.*value\])", text, re.DOTALL | re.IGNORECASE)
    sub_questions = sub_match.group(1).strip() if sub_match else "[]"
    return label, sub_questions


def strip_code_fence(text):
    text = text.strip()
    fence = re.findall(r"```(value:sql)value\s*(.*value)\s*```", text, re.DOTALL | re.IGNORECASE)
    if fence:
        return fence[-1].strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return text


def extract_prefixed_sql(text, prefixes=("Revised_SQL", "SQL")):
    for prefix in prefixes:
        pattern = rf"{prefix}\s*:\s*(.*)$"
        matches = list(re.finditer(pattern, text, re.DOTALL | re.IGNORECASE))
        if matches:
            return strip_code_fence(matches[-1].group(1)).strip()
    return strip_code_fence(text).strip()


def parse_response(response):
    return extract_prefixed_sql(response)


def safe_model_dir_name(model_name):
    return model_name.replace("/", "_").replace("\\", "_").replace(":", "_")


def get_stop_token_ids(model_path):
    if "Qwen2.5-" in model_path:
        return [151645]
    if "deepseek-coder-" in model_path:
        return [32021]
    if "DeepSeek-Coder-V2" in model_path:
        return [100001]
    if "OpenCoder-" in model_path:
        return [96539]
    if "Meta-Llama-" in model_path:
        return [128009, 128001]
    if "granite-" in model_path:
        return [0]
    if "starcoder2-" in model_path:
        return [0]
    if "Codestral-" in model_path:
        return [2]
    if "Mixtral-" in model_path:
        return [2]
    if "OmniSQL-" in model_path:
        return [151645]
    print("Use Qwen2.5's stop tokens by default.")
    return [151645]


def render_chat_prompts(tokenizer, prompts):
    return [
        tokenizer.apply_chat_template(
            [{"role": "user", "content": prompt}],
            add_generation_prompt=True,
            tokenize=False,
        )
        for prompt in prompts
    ]


def generate_texts(llm, tokenizer, sampling_params, prompts, stage_name):
    print(f"Running DIN-SQL stage: {stage_name} ({len(prompts)} prompts)")
    outputs = llm.generate(render_chat_prompts(tokenizer, prompts), sampling_params)
    return [output.outputs[0].text for output in outputs]


def build_results(cases, stage_outputs, method):
    results = []
    pred_sql = []
    for case, stages in zip(cases, stage_outputs):
        if method == "paper_zero_shot":
            final_sql = parse_response(stages["zero_shot"])
        else:
            final_sql = parse_response(stages["self_correction"])
        result_item = {
            "question_id": case.question_id,
            "db_id": case.db_id,
            "question": case.question,
            "evidence": case.evidence,
            "difficulty": case.difficulty,
            "ground_truth_sql": case.ground_truth_sql,
            "dialect": case.dialect,
            "method": method,
            "pred_sqls": [final_sql],
        }
        if method == "paper_zero_shot":
            result_item["zero_shot"] = stages["zero_shot"]
        else:
            result_item["schema_linking"] = stages["schema_linking"]
            result_item["classification"] = stages["classification"]
            result_item["sql_generation"] = stages["sql_generation"]
            result_item["self_correction"] = stages["self_correction"]
        pred_item = {
            "question_id": case.question_id,
            "db_id": case.db_id,
            "pred_sqls": [final_sql],
            "ground_truth_sql": case.ground_truth_sql,
            "difficulty": case.difficulty,
        }
        if case.annotation_source:
            result_item["annotation_source"] = case.annotation_source
            pred_item["annotation_source"] = case.annotation_source
        results.append(result_item)
        pred_sql.append(pred_item)
    return results, pred_sql


def run_paper_zero_shot(cases, llm, tokenizer, sampling_params):
    prompts = [paper_zero_shot_prompt(case) for case in cases]
    outputs = generate_texts(llm, tokenizer, sampling_params, prompts, "paper_zero_shot")
    return [{"zero_shot": output} for output in outputs]


def run_dinsql(cases, llm, tokenizer, sampling_params):
    schema_prompts = [schema_linking_prompt(case) for case in cases]
    schema_outputs = generate_texts(llm, tokenizer, sampling_params, schema_prompts, "schema_linking")
    schema_links = [extract_schema_links(text) for text in schema_outputs]

    class_prompts = [
        classification_prompt(case, links)
        for case, links in zip(cases, schema_links)
    ]
    class_outputs = generate_texts(llm, tokenizer, sampling_params, class_prompts, "classification")
    labels_and_subq = [extract_label_and_sub_questions(text) for text in class_outputs]

    sql_prompts = [
        sql_generation_prompt(case, links, label, sub_questions)
        for case, links, (label, sub_questions) in zip(cases, schema_links, labels_and_subq)
    ]
    sql_outputs = generate_texts(llm, tokenizer, sampling_params, sql_prompts, "sql_generation")
    generated_sqls = [extract_prefixed_sql(text, prefixes=("SQL",)) for text in sql_outputs]

    correction_prompts = [
        self_correction_prompt(case, sql_query)
        for case, sql_query in zip(cases, generated_sqls)
    ]
    correction_outputs = generate_texts(llm, tokenizer, sampling_params, correction_prompts, "self_correction")

    return [
        {
            "schema_linking": schema_output,
            "classification": class_output,
            "sql_generation": sql_output,
            "self_correction": correction_output,
        }
        for schema_output, class_output, sql_output, correction_output in zip(
            schema_outputs,
            class_outputs,
            sql_outputs,
            correction_outputs,
        )
    ]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    project_dir = Path(__file__).resolve().parent
    parser.add_argument("--model", type=str, default=None, help="model name under UNIQL_MODEL_ROOT")
    parser.add_argument("--pretrained_model_name_or_path", type=str, default=None)
    parser.add_argument("--input_file", type=str, default=str(project_dir / "data" / "hive.json"))
    parser.add_argument("--output_file", type=str, default=str(project_dir / "results-dinsql-zero-shot"))
    parser.add_argument("--tensor_parallel_size", type=int, default=4)
    parser.add_argument("--n", type=int, default=1, help="DIN-SQL zero-shot uses one reasoning chain; only n=1 is supported")
    parser.add_argument("--temperature", type=float, default=0)
    parser.add_argument("--schema_dir", type=str, default=str(project_dir / "schema"))
    parser.add_argument("--dialect", type=str, default="all")
    parser.add_argument("--max_model_len", type=int, default=8192)
    parser.add_argument("--max_input_len", type=int, default=2048)
    parser.add_argument("--max_output_len", type=int, default=6144)
    parser.add_argument("--limit", type=int, default=None, help="limit samples per dialect for quick checks")
    parser.add_argument(
        "--method",
        choices=["paper_zero_shot", "decomposed_zero_shot"],
        default="paper_zero_shot",
        help="paper_zero_shot matches the DIN-SQL paper's zero-shot baseline; decomposed_zero_shot is an experimental ablation",
    )
    parser.add_argument("--dry_run", action="store_true", help="validate prompts and paths without loading the model")
    args = parser.parse_args()

    args.dialect = normalize_dialect(args.dialect)
    if args.model:
        args.pretrained_model_name_or_path = str(Path(os.getenv('UNIQL_MODEL_ROOT', '<MODEL_ROOT>')) / args.model)
        args.output_file = str(Path(args.output_file) / args.model)
    elif not args.pretrained_model_name_or_path:
        args.pretrained_model_name_or_path = str(Path(os.getenv('UNIQL_MODEL_ROOT', '<MODEL_ROOT>')) / 'Qwen3-8B')

    print(args)

    questions = load_questions(args.input_file)
    test_cases = build_test_cases(questions, args.schema_dir, args.dialect)
    grouped_cases = {dialect: [] for dialect in SUPPORTED_DIALECTS}
    for case in test_cases:
        grouped_cases[case.dialect].append(case)

    output_dir = Path(args.output_file)
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.dry_run:
        print("Dry run completed successfully.")
        print(f"Loaded {len(questions)} questions and built {len(test_cases)} test cases.")
        print("Case counts:", {dialect: len(items) for dialect, items in grouped_cases.items() if items})
        first_case = next((items[0] for items in grouped_cases.values() if items), None)
        if first_case:
            if args.method == "paper_zero_shot":
                print("Sample paper zero-shot prompt preview:")
                print(paper_zero_shot_prompt(first_case)[:1500])
            else:
                print("Sample schema linking prompt preview:")
                print(schema_linking_prompt(first_case)[:1500])
        raise SystemExit(0)

    from transformers import AutoTokenizer
    from vllm import LLM, SamplingParams

    tokenizer = AutoTokenizer.from_pretrained(args.pretrained_model_name_or_path, trust_remote_code=True)
    stop_token_ids = get_stop_token_ids(args.pretrained_model_name_or_path)
    print("stop_token_ids:", stop_token_ids)

    if args.max_input_len + args.max_output_len > args.max_model_len:
        raise ValueError(
            f"Invalid length configuration: max_input_len({args.max_input_len}) + "
            f"max_output_len({args.max_output_len}) > max_model_len({args.max_model_len})"
        )

    sampling_params = SamplingParams(
        temperature=args.temperature,
        max_tokens=args.max_output_len,
        n=1,
        stop_token_ids=stop_token_ids,
    )

    llm = LLM(
        model=args.pretrained_model_name_or_path,
        dtype="float16",
        tensor_parallel_size=args.tensor_parallel_size,
        max_model_len=args.max_model_len,
        gpu_memory_utilization=0.92,
        swap_space=0,
        enforce_eager=True,
        disable_custom_all_reduce=True,
        trust_remote_code=True,
    )

    selected_dialects = [dialect for dialect, items in grouped_cases.items() if items]
    if not selected_dialects:
        raise ValueError(f"No samples with golden SQL for dialect={args.dialect} were found in {args.input_file}.")

    for dialect in selected_dialects:
        cases = grouped_cases[dialect]
        if args.limit is not None:
            cases = cases[:args.limit]
        print(f"Generating {dialect} SQL for {len(cases)} samples with method={args.method}...")
        if args.method == "paper_zero_shot":
            stage_outputs = run_paper_zero_shot(cases, llm, tokenizer, sampling_params)
        else:
            stage_outputs = run_dinsql(cases, llm, tokenizer, sampling_params)
        results, pred_sql = build_results(cases, stage_outputs, args.method)

        with open(output_dir / f"{dialect}_dev.json", "w", encoding="utf-8") as file:
            file.write(json.dumps(results, indent=2, ensure_ascii=False))
        with open(output_dir / f"{dialect}_pred_sql.json", "w", encoding="utf-8") as file:
            file.write(json.dumps(pred_sql, indent=2, ensure_ascii=False))



