import argparse
import json
import os
import concurrent.futures
from config import INPUT_DATA_PATH, RULES_DIR
from validator import Validator
from rule_optimizer import RuleOptimizer
from tqdm import tqdm

def load_data(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_results(results, path):
    # results is a dict or listvalue BIRD expects a format
    # The user asked to record success in annotation_source field.
    # We will save the list of result objects.
    
    # Sort by question_id if possible
    if isinstance(results, list):
        try:
            results.sort(key=lambda x: x.get('question_id', 0))
        except Exception as e:
            print(f"Warning: Could not sort results: {e}")

    with open(path, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=4, ensure_ascii=False)

def main():
    parser = argparse.ArgumentParser(description="UniQL SQL Translation")
    parser.add_argument('--source', type=str, default='sqlite', help='Source dialect (e.g., sqlite)')
    parser.add_argument('--target', type=str, required=True, help='Target dialect (e.g., mysql, postgresql)')
    parser.add_argument('--workers', type=int, default=10, help='Parallel threads')
    parser.add_argument('--limit', type=int, default=None, help='Limit number of queries for testing')
    parser.add_argument('--iteration', type=int, default=1, help='Number of rule optimization rounds')
    args = parser.parse_args()
    
    source_dialect = args.source
    target_dialect = args.target
    
    print(f"Starting Translation: {source_dialect} -> {target_dialect}")
    
    # 1. Load Data
    full_data = load_data(INPUT_DATA_PATH)
    if args.limit:
        full_data = full_data[:args.limit]
    
    print(f"Loaded {len(full_data)} entries.")
    
    # 2. Setup Components
    optimizer = RuleOptimizer(RULES_DIR)
    
    # Load existing rules (if any)
    initial_rules = optimizer.load_rules(source_dialect, target_dialect)
    
    validator = Validator(source_dialect, target_dialect, initial_rules)
    
    # 3. Resume from previous run or Start fresh
    # Check if a partial or full result exists to resume stats/iterations
    results_dir = './results'
    if not os.path.exists(results_dir):
        os.makedirs(results_dir)
        
    result_json_path = os.path.join(results_dir, f"results_{source_dialect}_{target_dialect}.json")
    exp_log_path = os.path.join(results_dir, f"experiment_results_{source_dialect}_{target_dialect}.txt")
    
    start_results = {}
    prev_iteration_count = 0
    
    # Helper for conventions
    convention_map = {
        'mysql': 'SQL-mysql', 
        'postgresql': 'SQL-PostgreSQL', 
        'oracle': 'SQL-Oracle', 
        'mssql': 'SQL-MSSQL', 
        'hive': 'SQL-Hive',
        'sqlite': 'SQL-sqlite'
    }
    
    if os.path.exists(result_json_path):
        print(f"Resuming from existing results: {result_json_path}")
        try:
            existing_data = load_data(result_json_path)
            # existing_data is a list of result objects
            for item in existing_data:
                qid = item['question_id']
                start_results[qid] = item
                
            # Try to infer previous iteration count from log file
            if os.path.exists(exp_log_path):
                with open(exp_log_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    # Parse last line like "1         | 1534 ..."
                    # Skip header lines
                    for line in reversed(lines):
                         if line.strip() and "|" in line and "Iteration" not in line and "---" not in line:
                             parts = line.split("|")
                             try:
                                 prev_iteration_count = int(parts[0].strip())
                                 print(f"Detected previous max iteration: {prev_iteration_count}")
                                 break
                             except: pass
        except Exception as e:
            print(f"Error loading previous results: {e}. Starting fresh.")
            start_results = {}

    failed_entries = []
    to_process_indices = []
    
    # We filter what needs to be validated/processed
    # 1. New entries (not in start_results)
    # 2. Failed entries (in start_results but incorrect) - these go to failed_entries for Optimization
    
    for entry in full_data:
        qid = entry['question_id']
        
        if qid in start_results:
            res = start_results[qid]
            tool = res.get('annotation_source', 'failed')
            if tool != 'failed':
                continue # Already done and success
            else:
                failed_entries.append(entry) # Needs optimization
        else:
             to_process_indices.append(entry) # Needs Round 1

    error_logs = []
    
    # helper to track progress
    last_success_count = sum(1 for res in start_results.values() if res.get('annotation_source') != 'failed')
    
    def save_experiment_log(iteration_label, current_success, newly_fixed):
        log_file = os.path.join(results_dir, f"experiment_results_{source_dialect}_{target_dialect}.txt")
        token_stats = validator.translator.token_stats
        
        # Calculate rates
        success_rate = (current_success / len(full_data) * 100) if full_data else 0.0
        
        header = "Experiment: {} -> {}\n".format(source_dialect, target_dialect)
        header += "Iteration | Total Success | Success Rate | Newly Fixed | Glot | LLM-0shot | LLM-Retry | LLM-Rule | Total Token | Prompt Token | Completion Token\n"
        header += "-" * 130 + "\n"
        
        exists = os.path.exists(log_file)
        with open(log_file, 'a', encoding='utf-8') as f:
            if not exists:
                f.write(header)
            
            row = "{:<9} | {:<13} | {:<12.1f}% | {:<11} | {:<4} | {:<9} | {:<9} | {:<8} | {:<11,} | {:<12,} | {:<16,}\n".format(
                iteration_label, 
                current_success,
                success_rate,
                newly_fixed,
                validator.stats['success_glot'],
                validator.stats['success_llm_0shot'],
                validator.stats['success_llm_retry'],
                validator.stats['success_llm_rule'],
                token_stats['total'],
                token_stats['prompt'],
                token_stats['completion']
            )
            f.write(row)
        print(f"Logged stats for Iteration {iteration_label}")

    def process_entry(entry, use_rules=False):
        success, info = validator.validate_single(entry, use_rules=use_rules)
        return entry, success, info

    # Round 1: Initial Translation
    if to_process_indices:
        print(f"\n--- Round 1: Initial Translation ({len(to_process_indices)} new entries) ---")
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {executor.submit(process_entry, entry, use_rules=False): entry for entry in to_process_indices}
            
            for future in tqdm(concurrent.futures.as_completed(futures), total=len(futures)):
                entry, success, info = future.result()
                qid = entry['question_id']
                
                # res_obj construction
                res_obj = entry.copy()
                if 'SQL' in res_obj:
                    res_obj['SQL-sqlite'] = res_obj.pop('SQL')
                
                target_key = convention_map.get(target_dialect.lower(), f"SQL-{target_dialect}")
                
                res_obj[target_key] = info.get('translated_sql', '')
                try:
                    res_obj['annotation_source'] = info.get('annotation_source', 'failed')
                except:
                    res_obj['annotation_source'] = 'failed'
                
                if success:
                    start_results[qid] = res_obj
                else:
                    failed_entries.append(entry) 
                    # Log error for optimization
                    db_id = entry['db_id']
                    schema_info = validator.get_cached_schema(db_id)
                    if len(schema_info) > 2000:
                        schema_info = schema_info[:2000] + "...(truncated)"
                    
                    err_msg = info.get('error', '')
                    if len(err_msg) > 3000:
                        err_msg = err_msg[:3000] + "...(truncated)"
                        
                    error_log = f"QID: {qid}\nQuestion: {entry['question']}\nSource SQL: {entry['SQL']}\nDB: {db_id}\nTarget Schema:\n{schema_info}\nFailure Log:\n{err_msg}\n{'-'*20}"
                    error_logs.append(error_log)
        
        # Save results
        save_results(list(start_results.values()), result_json_path)
        
        # Log Iteration 0 (Initial) only if it's the first run evervalue No, if we ran fresh, we log.
        # If we resumed and ran *some* new Round 1, we log.
        current_success = sum(1 for res in start_results.values() if res.get('annotation_source') != 'failed')
        newly_fixed = current_success - last_success_count
        save_experiment_log(prev_iteration_count, current_success, newly_fixed)
        last_success_count = current_success
    else:
        # If we didn't run Round 1 because all done, we don't necessarily log "0" again unless asked.
        # But if we resume and jump to Loop, that's fine.
        pass

    print(f"Round 1 (New) Stats: {validator.stats}")
    print(f"Total Pending Failures: {len(failed_entries)}")
    
    # ... (Resume failed entries check - omitted for brevity, unchanged logic essentially) ...
    # Wait, the tool 'replace string' must match strictly. 
    # The previous code had the resumption logic. I'll preserve it or assume it's there.
    # Actually, I should just paste the resumption logic here too or rely on `if failed_entries and not error_logs`.
    # Let's include the resumption block in the replacement to be safe.
    
    if failed_entries and not error_logs:
         print("Resuming with failed entries... Generating error logs for optimization context.")
         with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {executor.submit(process_entry, entry, use_rules=False): entry for entry in failed_entries}
            
            for future in tqdm(concurrent.futures.as_completed(futures), total=len(futures)):
                entry, success, info = future.result()
                qid = entry['question_id']
                if success:
                     res_obj = entry.copy()
                     if 'SQL' in res_obj: res_obj['SQL-sqlite'] = res_obj.pop('SQL')
                     target_key = convention_map.get(target_dialect.lower(), f"SQL-{target_dialect}")
                     res_obj[target_key] = info.get('translated_sql', '')
                     res_obj['annotation_source'] = info.get('annotation_source', 'failed')
                     start_results[qid] = res_obj
                else:
                    db_id = entry['db_id']
                    schema_info = validator.get_cached_schema(db_id)
                    if len(schema_info) > 2000: schema_info = schema_info[:2000] + "..."
                    err_msg = info.get('error', '')
                    if len(err_msg) > 3000: err_msg = err_msg[:3000] + "..."
                    error_log = f"QID: {qid}\nQuestion: {entry['question']}\nSource SQL: {entry['SQL']}\nDB: {db_id}\nTarget Schema:\n{schema_info}\nFailure Log:\n{err_msg}\n{'-'*20}"
                    error_logs.append(error_log)
         
         real_failures = []
         for entry in failed_entries:
             if entry['question_id'] in start_results and start_results[entry['question_id']].get('annotation_source') != 'failed':
                 continue
             real_failures.append(entry)
         failed_entries = real_failures
         
         # Note: We don't log stats here because this is just "warm up" not a real iteration improvement.
         # But if it fixed things miraculously, `last_success_count` should updatevalue
         current_success = sum(1 for res in start_results.values() if res.get('annotation_source') != 'failed')
         if current_success > last_success_count:
             last_success_count = current_success # Silent update or proper logvalue
             # Let's silent update so next real iteration gets creditvalue Or just logvalue
             # Probably just update tracker.
         
    if not failed_entries:
        print("All queries successfully translated!")
        final_list = list(start_results.values())
        if not os.path.exists(results_dir):
            os.makedirs(results_dir)
        output_path = os.path.join(results_dir, f"results_{source_dialect}_{target_dialect}.json")
        save_results(final_list, output_path)
    
    # 4. Optimization Loop
    current_failed = failed_entries
    
    start_iter = prev_iteration_count + 1
    end_iter = start_iter + args.iteration
    
    for round_idx in range(start_iter, end_iter):
        if not current_failed:
            print("No more failures to optimize.")
            # Still logs the statevalue
            current_success = sum(1 for res in start_results.values() if res.get('annotation_source') != 'failed')
            newly_fixed = current_success - last_success_count
            save_experiment_log(round_idx, current_success, newly_fixed)
            break
            
        print(f"\n--- Optimization Round {round_idx} ---")
        
        # Optimize based on current failures
        # Extract logs from the last attempt for these failed entries
        # Current logic in 'process_entry' doesn't return logs easily for outside access except via 'error_logs' list accumulation
        # But 'error_logs' list was built during Round 1. We need fresh logs for subsequent rounds.
        # Let's rebuild error logs from the 'current_failed' (failed_entries) which were populated in previous step.
        # Wait, 'failed_entries' is a list of data dicts. 'error_logs' was a separate list of strings.
        # If we loop, we need to capture the NEW error logs from the Retry step to feed into the NEXT Optimization.
        
        # On first iteration (Round 1), 'error_logs' is already populated from Round 1.
        # On subsequent iterations, we need logs from the PREVIOUS Retry.
        
        if round_idx > 0:
            pass

        # Collect unique schemas involved in failures to pass to optimizer
        unique_db_ids = set()
        for log_entry in current_failed: # current_failed contains original entries
            unique_db_ids.add(log_entry.get('db_id'))
            
        combined_schema_info = ""
        for db_id in sorted(list(unique_db_ids))[:5]: # Limit to 5 DBs to avoid huge contextvalue
             # Or maybe just list namesvalue No, template asks for schemas.
             s = validator.get_cached_schema(db_id)
            #  if len(s) > 1000: s = s[:1000] + "...(truncated)"
             combined_schema_info += f"--- Schema for DB: {db_id} ---\n{s}\n\n"
        
        optimizer.optimize(source_dialect, target_dialect, error_logs, schema_info=combined_schema_info)
        
        # Reload Rules (Optimized)
        updated_rules = optimizer.load_rules(source_dialect, target_dialect)
        validator.rules = updated_rules # Update validator's rules
        
        # Retry with Rules
        print(f"Retrying {len(current_failed)} failed entries with New Rules...")
        
        next_failed = []
        next_error_logs = []
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
            # Pass use_rules=True 
            futures = {executor.submit(process_entry, entry, use_rules=True): entry for entry in current_failed}
            
            for future in tqdm(concurrent.futures.as_completed(futures), total=len(futures)):
                entry, success, info = future.result()
                qid = entry['question_id']
                
                # Reconstruct res_obj with same logic as above
                res_obj = entry.copy()
                if 'SQL' in res_obj:
                    res_obj['SQL-sqlite'] = res_obj.pop('SQL')
                
                target_key = convention_map.get(target_dialect.lower(), f"SQL-{target_dialect}")
                
                res_obj[target_key] = info.get('translated_sql', '')
                res_obj['annotation_source'] = info.get('annotation_source', 'failed')
                
                if success:
                    start_results[qid] = res_obj
                else:
                    # Still failed
                    start_results[qid] = res_obj 
                    next_failed.append(entry)
                    
                    db_id = entry['db_id']
                    schema_info = validator.get_cached_schema(db_id)
                    if len(schema_info) > 2000: schema_info = schema_info[:2000] + "..."
                    
                    err_msg = info.get('error', '')
                    if len(err_msg) > 3000: err_msg = err_msg[:3000] + "..."
                    
                    error_log = f"QID: {qid}\nQuestion: {entry['question']}\nSource SQL: {entry['SQL']}\nDB: {entry['db_id']}\nTarget Schema:\n{schema_info}\nFailure Log:\n{err_msg}\n{'-'*20}"
                    next_error_logs.append(error_log)
        
        current_failed = next_failed
        error_logs = next_error_logs
        print(f"Round {round_idx} Done. Remaining Failures: {len(current_failed)}")
        
        # Log Stats for this round
        current_success = sum(1 for res in start_results.values() if res.get('annotation_source') != 'failed')
        newly_fixed = current_success - last_success_count
        save_experiment_log(round_idx, current_success, newly_fixed)
        last_success_count = current_success

    # Calculate Total Cumulative Stats (Unique Queries)
    total_success_cumulative = sum(1 for res in start_results.values() if res.get('annotation_source') != 'failed')
    total_processed = len(full_data)
    final_failed_count = total_processed - total_success_cumulative
    success_rate = (total_success_cumulative / total_processed * 100) if total_processed else 0.0

    print(f"\nOptimization Finished.")
    print(f"Session Execution Stats (Includes Retries): {validator.stats}")
    print(f"Final Dataset Stats (Unique Queries): {{'total': {total_processed}, 'success': {total_success_cumulative}, 'failed': {final_failed_count}}}")
    
    # Final cleanup logic (output file saving) is handled inside the loop or after
    # But we want to ensure JSON results are saved finally
    final_output = list(start_results.values())
    output_path = os.path.join(results_dir, f"results_{source_dialect}_{target_dialect}.json")
    save_results(final_output, output_path)
    print(f"Results saved to {output_path}")

if __name__ == "__main__":
    main()


