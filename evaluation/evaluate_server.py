import os
import sys
import json
import argparse
import sqlite3
import importlib.util
import multiprocessing as mp
import time
from pathlib import Path
from collections import defaultdict
from datetime import date, datetime, timedelta
from func_timeout import func_timeout, FunctionTimedOut
from decimal import Decimal


SPECIAL_SEPERATOR = "\t----- SQL-EVAL -----\t"
SPECIAL_SEPERATOR_BIRD = "\t----- bird -----\t"

DIALECT_ALIASES = {
    "sqlite": "sqlite",
    "mysql": "mysql",
    "oracle": "oracle",
    "postgre": "postgresql",
    "postgresql": "postgresql",
    "hive": "hive",
    "clickhouse": "clickhouse",
    "duckdb": "duckdb",
    "presto": "presto",
    "druid": "druid",
}



def load_json(dir):
    with open(dir, 'r') as j:
        contents = json.loads(j.read())
    return contents

def read_to_text_list(path, encoding='utf-8'):
    list_line = []
    if not os.path.exists(path):
        return list_line
    with open(path, 'r', encoding=encoding) as f:
        list_line = f.readlines()
        list_line = [row.rstrip("\n") for row in list_line]
        return list_line


def result_callback(result):
    exec_result.append(result)


def normalize_dialect(dialect):
    normalized = DIALECT_ALIASES.get(dialect.lower())
    if normalized is None:
        raise ValueError(f"Unsupported dialect: {dialect}")
    return normalized


def validate_runtime(dialect):
    required_modules = {
        "sqlite": [],
        "mysql": ["pymysql"],
        "oracle": ["oracledb"],
        "postgresql": ["psycopg2"],
        "hive": [],
        "clickhouse": ["clickhouse_connect"],
        "duckdb": ["duckdb"],
        "presto": [],
        "druid": ["requests"],
    }
    missing = [
        module_name for module_name in required_modules[dialect]
        if importlib.util.find_spec(module_name) is None
    ]
    if missing:
        raise RuntimeError(
            f"Missing required package(s) for {dialect} evaluation: {', '.join(missing)}"
        )


def execute_sql(predicted_sql, ground_truth, db_path,dialect='sqlite'):
    dialect = normalize_dialect(dialect)
    if dialect=='sqlite':
        from sqlite_eval import SQLiteEvaluator
        res,gt_result,pred_result = SQLiteEvaluator(db_path,ground_truth,predicted_sql).check_result_same()
    elif dialect=="mysql":
        from mysql_eval import MySQLEvaluator
        res,gt_result,pred_result = MySQLEvaluator(db_path,ground_truth,predicted_sql).check_result_same()
    elif dialect=="oracle":
        from oracle_eval import OracleEvaluater
        res,gt_result,pred_result = OracleEvaluater(db_path,ground_truth,predicted_sql).check_result_same()
    elif dialect=="postgresql":
        from postgre_eval import PostgreEvaluator
        res,gt_result,pred_result = PostgreEvaluator(db_path,ground_truth,predicted_sql).check_result_same()
    elif dialect=="hive":
        from hive_eval import HiveEvaluator
        res,gt_result,pred_result = HiveEvaluator(db_path,ground_truth,predicted_sql).check_result_same()
    elif dialect=="clickhouse":
        from clickhouse_eval import ClickHouseEvaluator
        res,gt_result,pred_result = ClickHouseEvaluator(db_path,ground_truth,predicted_sql).check_result_same()
    elif dialect=="duckdb":
        from duckdb_eval import DuckDBEvaluator
        res,gt_result,pred_result = DuckDBEvaluator(db_path,ground_truth,predicted_sql).check_result_same()
    elif dialect=="presto":
        from presto_eval import PrestoEvaluator
        res,gt_result,pred_result = PrestoEvaluator(db_path,ground_truth,predicted_sql).check_result_same()
    elif dialect=="druid":
        from druid_eval import DruidEvaluator
        res,gt_result,pred_result = DruidEvaluator(db_path,ground_truth,predicted_sql).check_result_same()
    return res, gt_result,pred_result

#     start_time = time.time()
#     conn = sqlite3.connect(db_path)
#     # Connect to the database
#     cursor = conn.cursor()

#     # Execute predicted SQL and measure time
#     pred_start = time.time()
#     cursor.execute(predicted_sql)
#     predicted_res = cursor.fetchall()
#     pred_time = time.time() - pred_start

#     # Execute ground truth SQL and measure time
#     gt_start = time.time()
#     cursor.execute(ground_truth)
#     ground_truth_res = cursor.fetchall()
#     gt_time = time.time() - gt_start

#     total_time = time.time() - start_time
#     res = 0
#     if set(predicted_res) == set(ground_truth_res):
#         res = 1

#     return res, ground_truth_res,predicted_res

def execute_model(predicted_sql, ground_truth, db_place, idx, meta_time_out,dialect='sqlite'):
    start_timestamp = datetime.now().isoformat()
    try:
        res, gt_result,pred_result = func_timeout(meta_time_out, execute_sql,
                                                           args=(predicted_sql, ground_truth, db_place,dialect))
        timeout = False
        error = None
    except KeyboardInterrupt:
        sys.exit(0)
    except FunctionTimedOut:
        result = [(f'timeout',)]
        res = 0
        timeout = True
        error = 'timeout'
        pred_result = []
        gt_result = []
    except Exception as e:
        result = [(f'error',)]  # possibly len(query) > 512 or not executable
        res = 0
        timeout = False
        error = str(e)
        pred_result = []
        gt_result = []

    result = {
        'sql_idx': idx,
        'res': res,
        'start_timestamp': start_timestamp,
        'timeout': timeout,
        'error': error,
        'predicted_sql': predicted_sql,
        'ground_truth_sql': ground_truth,
        'pred_result': pred_result,
        'gt_result': gt_result
    }
    return result


def package_sqls(sql_path:str, db_root_path, dev_path=None):
    pred_sqls = []
    gt_sqls = []
    db_path_list = []
    metadata = []

    pred_data = load_json(sql_path)

    for idx, sql_str in enumerate(pred_data):
        pred_sqls_list = sql_str.get("pred_sqls", [])
        pred_sql = pred_sqls_list[0] if pred_sqls_list else ""
        db_name = sql_str.get("db_id","")
        gt_sql = sql_str.get("ground_truth_sql","")
        pred_sqls.append(pred_sql)
        gt_sqls.append(gt_sql)
        db_path_list.append(str(Path(db_root_path) / db_name / f"{db_name}.sqlite"))
        metadata.append({
            "question_id": sql_str.get("question_id", ""),
            "difficulty": sql_str.get("difficulty", ""),
            "annotation_source": sql_str.get("annotation_source", "unknown"),
            "db_id": db_name,
        })
    print(f"load data total {len(pred_sqls)} from {sql_path}")
    print(f"load gt sql total {len(gt_sqls)} from {sql_path}")
    return pred_sqls, gt_sqls, db_path_list, metadata


def run_sqls_parallel(sqls, db_places, num_cpus=1, meta_time_out=120.0,dialect='sqlite'):
    pool = mp.Pool(processes=num_cpus)
    for i, sql_pair in enumerate(sqls):
        predicted_sql, ground_truth = sql_pair
        pool.apply_async(execute_model, args=(predicted_sql, ground_truth, db_places[i], i, meta_time_out,dialect),
                         callback=result_callback)
    pool.close()
    pool.join()


def sort_results(list_of_dicts):
    return sorted(list_of_dicts, key=lambda x: x['sql_idx'])


def save_timing_results(exec_results, output_path='sql_execution_timing_results.json'):
    """Save detailed timing results to JSON file"""
    timing_data = {
        'evaluation_summary': {
            'total_queries': len(exec_results),
            'successful_executions': sum(1 for r in exec_results if r['res'] == 1),
            'timeout_count': sum(1 for r in exec_results if r['timeout']),
            'error_count': sum(1 for r in exec_results if r['error'] and not r['timeout']),
            'evaluation_timestamp': datetime.now().isoformat()
        },
        'timing_statistics': {
            'total_pred_time': sum(r['predicted_sql_time'] for r in exec_results),
            'total_gt_time': sum(r['ground_truth_sql_time'] for r in exec_results),
            'total_execution_time': sum(r['total_execution_time'] for r in exec_results),
            'avg_pred_time': sum(r['predicted_sql_time'] for r in exec_results) / len(exec_results) if exec_results else 0,
            'avg_gt_time': sum(r['ground_truth_sql_time'] for r in exec_results) / len(exec_results) if exec_results else 0,
            'avg_total_time': sum(r['total_execution_time'] for r in exec_results) / len(exec_results) if exec_results else 0
        },
        'detailed_results': exec_results
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(timing_data, f, indent=2, ensure_ascii=False)

    print(f"\nTiming results saved to: {output_path}")
    print(f"Total predicted SQL execution time: {timing_data['timing_statistics']['total_pred_time']:.4f}s")
    print(f"Total ground truth SQL execution time: {timing_data['timing_statistics']['total_gt_time']:.4f}s")
    print(f"Total evaluation time: {timing_data['timing_statistics']['total_execution_time']:.4f}s")


def compute_acc_by_diff(exec_results, metadata):
    num_queries = len(exec_results)
    print(f"Total number of queries evaluated: {num_queries}")
    results = [res['res'] for res in exec_results]
    simple_results, moderate_results, challenging_results = [], [], []
    for i, content in enumerate(metadata):
        if content['difficulty'] == 'simple':
            simple_results.append(exec_results[i])
        elif content['difficulty'] == 'moderate':
            moderate_results.append(exec_results[i])
        elif content['difficulty'] == 'challenging':
            challenging_results.append(exec_results[i])
    num_queries = len(simple_results)+len(moderate_results)+len(challenging_results)
    simple_acc = sum([res['res'] for res in simple_results]) / len(simple_results) if simple_results else 0
    moderate_acc = sum([res['res'] for res in moderate_results]) / len(moderate_results) if moderate_results else 0
    challenging_acc = sum([res['res'] for res in challenging_results]) / len(challenging_results) if challenging_results else 0
    all_acc = sum(results) / num_queries if num_queries > 0 else 0
    count_lists = [len(simple_results), len(moderate_results), len(challenging_results), num_queries]
    return simple_acc * 100, moderate_acc * 100, challenging_acc * 100, all_acc * 100, count_lists

def compute_acc_by_tool(exec_results, metadata):
    grouped_results = defaultdict(list)
    for result, meta in zip(exec_results, metadata):
        grouped_results[meta.get("annotation_source", "unknown")].append(result)

    tool_names = sorted(grouped_results.keys())
    score_lists = []
    count_lists = []
    for tool_name in tool_names:
        tool_results = grouped_results[tool_name]
        score_lists.append(sum(x["res"] for x in tool_results) / len(tool_results) * 100 if tool_results else 0)
        count_lists.append(len(tool_results))

    tool_names.append("total")
    score_lists.append(sum(x["res"] for x in exec_results) / len(exec_results) * 100 if exec_results else 0)
    count_lists.append(len(exec_results))
    return tool_names, score_lists, count_lists


def print_tool_data(tool_names, score_lists, count_lists):
    col_width = 20
    print("".ljust(col_width) + "".join(name.ljust(col_width) for name in tool_names))
    print("count".ljust(col_width) + "".join(str(count).ljust(col_width) for count in count_lists))
    print('========================    ACCURACY by annotation_source    ========================')
    print("accuracy".ljust(col_width) + "".join(f"{score:.2f}".ljust(col_width) for score in score_lists))

def print_data(score_lists, count_lists):
    levels = ['simple', 'moderate', 'challenging', 'total']
    print("{:20} {:20} {:20} {:20} {:20}".format("", *levels))
    print("{:20} {:<20} {:<20} {:<20} {:<20}".format('count', *count_lists))

    print('======================================    ACCURACY    =====================================')
    print("{:20} {:<20.2f} {:<20.2f} {:<20.2f} {:<20.2f}".format('accuracy', *score_lists))

def json_safe(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if isinstance(obj, timedelta):
        return str(obj)
    if isinstance(obj, bytes):
        try:
            return obj.decode('utf-8')
        except Exception:
            return obj.decode('utf-8', errors='replace')
    if isinstance(obj, (list, tuple)):
        return [json_safe(v) for v in obj]
    if isinstance(obj, dict):
        return {k: json_safe(v) for k, v in obj.items()}
    try:
        json.dumps(obj)
    except TypeError:
        return str(obj)
    return obj


def format_diff_summary(score_lists, count_lists):
    levels = ['simple', 'moderate', 'challenging', 'total']
    lines = [
        f"{'':20} " + " ".join(f"{level:20}" for level in levels),
        "{:20} {:<20} {:<20} {:<20} {:<20}".format('count', *count_lists),
        '======================================    ACCURACY    =====================================',
        "{:20} {:<20.2f} {:<20.2f} {:<20.2f} {:<20.2f}".format('accuracy', *score_lists),
    ]
    return "\n".join(lines)


def format_tool_summary(tool_names, score_lists, count_lists):
    col_width = 20
    lines = [
        "".ljust(col_width) + "".join(name.ljust(col_width) for name in tool_names),
        "count".ljust(col_width) + "".join(str(count).ljust(col_width) for count in count_lists),
        '========================    ACCURACY by annotation_source    ========================',
        "accuracy".ljust(col_width) + "".join(f"{score:.2f}".ljust(col_width) for score in score_lists),
    ]
    return "\n".join(lines)


def save_summary_text(output_dir, dialect, model, num_queries, diff_summary, tool_summary):
    output_name = f"{dialect}.txt"
    summary_path = Path(output_dir) / output_name
    summary_text = "\n".join([
        f"Model: {model}",
        f"Dialect: {dialect}",
        f"Total number of queries evaluated: {num_queries}",
        "",
        "start calculate",
        diff_summary,
        tool_summary,
        "===========================================================================================",
        "Finished evaluation",
        "",
    ])
    with open(summary_path, 'w', encoding='utf-8') as f:
        f.write(summary_text)
    return summary_path


if __name__ == '__main__':
    args_parser = argparse.ArgumentParser()
    args_parser.add_argument('--predicted_sql_path', type=str, required=True, default='')
    args_parser.add_argument('--db_root_path', type=str, required=False, default=os.getenv('UNIQL_BIRD_DB_ROOT', '<BIRD_DEV_DATABASES>'))
    args_parser.add_argument('--num_cpus', type=int, default=1)
    args_parser.add_argument('--meta_time_out', type=float, default=120.0)
    args_parser.add_argument('--dialect', type=str, default='sqlite')
    args_parser.add_argument("--model",type=str,default='qwen3-8B')
    args_parser.add_argument('--output_dir', type=str, default='evaluation_results')
    # args_parser.add_argument('--timing_output_path', type=str, default='sql_execution_timing_results.json',
    #                        help='Path to save timing results in JSON format')
    args = args_parser.parse_args()
    args.dialect = normalize_dialect(args.dialect)
    validate_runtime(args.dialect)
    exec_result = []
    pred_queries, gt_queries, db_paths, metadata = package_sqls(args.predicted_sql_path, args.db_root_path)
    # generate gt sqls:
    # gt_queries, db_paths_gt = package_sqls(args.ground_truth_path, args.db_root_path, mode='gt',
    #                                        data_mode=args.data_mode)

    query_pairs = list(zip(pred_queries, gt_queries))
    assert len(query_pairs) == len(pred_queries) == len(gt_queries)
    run_sqls_parallel(query_pairs, db_places=db_paths, num_cpus=args.num_cpus, meta_time_out=args.meta_time_out,dialect=args.dialect)
    exec_result = sort_results(exec_result)
    
    # Save timing results to JSON
    # save_timing_results(exec_result, args.timing_output_path)

    print('start calculate')
    simple_acc, moderate_acc, challenging_acc, acc, count_lists = \
        compute_acc_by_diff(exec_result, metadata)
    score_lists = [simple_acc, moderate_acc, challenging_acc, acc]
    print_data(score_lists, count_lists)
    tool_names, tool_scores, tool_counts = compute_acc_by_tool(exec_result, metadata)
    print_tool_data(tool_names, tool_scores, tool_counts)
    output_dir = Path(args.output_dir) / f'{args.model}'
    output_dir.mkdir(parents=True, exist_ok=True)
    with open(output_dir / f"{args.dialect}_{args.model}.json",'w',encoding='utf-8') as f:
        json.dump(json_safe(exec_result), f, indent=2, ensure_ascii=False)
    diff_summary = format_diff_summary(score_lists, count_lists)
    tool_summary = format_tool_summary(tool_names, tool_scores, tool_counts)
    summary_path = save_summary_text(output_dir, args.dialect, args.model, len(exec_result), diff_summary, tool_summary)
    print(f"Saved evaluation summary to: {summary_path}")

    print('===========================================================================================')
    print("Finished evaluation")
'''
python eval.py \
    --predicted_sql_path <PREDICTION_FILE> \
    --db_root_path <BIRD_DEV_DATABASES> \
    --num_cpus 8 \
    --meta_time_out 240 \
    --dialect hive
'''



