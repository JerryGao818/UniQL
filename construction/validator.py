import concurrent.futures
import threading
import signal
import sqlglot
from db_manager import DBManager
from translator import SQLTranslator
from utils import check_result_same

# SQLGlot Dialect Map
GLOT_DIALECT_MAP = {
    'sqlite': 'sqlite',
    'mysql': 'mysql',
    'postgresql': 'postgres',
    'oracle': 'oracle',
    'hive': 'hive',
    'mssql': 'tsql'
}

class Validator:
    def __init__(self, source_dialect, target_dialect, rules):
        self.source_dialect = source_dialect
        self.target_dialect = target_dialect
        self.rules = rules
        
        self.db_manager = DBManager()
        self.translator = SQLTranslator()
        
        self.schema_cache = {}
        self.schema_lock = threading.Lock()
        
        self.stop_event = threading.Event()
        
        # Statistics
        self.stats = {
            'total': 0,
            'success_glot': 0,
            'success_llm_0shot': 0,
            'success_llm_retry': 0,
            'success_llm_rule': 0,
            'failed': 0
        }
        self.stats_lock = threading.Lock()

    def get_cached_schema(self, db_id):
        with self.schema_lock:
            if db_id not in self.schema_cache:
                # Fetch schema from TARGET database
                self.schema_cache[db_id] = self.db_manager.get_schema(self.target_dialect, db_id)
            return self.schema_cache[db_id]

    def validate_single(self, entry, use_rules=False):
        """
        Process a single entry.
        Returns: (success: bool, result_info: dict)
        result_info contains: 'translated_sql', 'error', 'annotation_source'
        """
        if self.stop_event.is_set():
            return False, {}

        qid = entry.get('question_id')
        db_id = entry.get('db_id')
        question = entry.get('question', '')
        
        # Source SQL (SQLite)
        source_sql = entry.get('SQL')
        
        if not source_sql:
            return False, {'error': 'No Source SQL'}

        # 1. Execute Source SQL on Source DB to get Ground Truth Result
        # Source is usually SQLite in BIRD Dev
        res_gt, err_gt = self.db_manager.execute_query(self.source_dialect, db_id, source_sql)
        
        if res_gt is None:
             with self.stats_lock: 
                 self.stats['failed'] += 1
                 self.stats['total'] += 1
             return False, {'error': f"Source Execution Failed: {err_gt}"}
        
        check_order = "order by" in source_sql.lower()

        # 2. Get Target Schema
        schema = self.get_cached_schema(db_id)
        if schema.startswith("Error"):
             with self.stats_lock:
                 self.stats['failed'] += 1
                 self.stats['total'] += 1
             return False, {'error': f"Schema Error: {schema}"}

        # ==========================================
        # Strategy A: Pure SQLGlot
        # ==========================================
        # Only try Glot if NOT using rules (optimization pass usually skips Glot or we can re-verify)
        # Actually, if Glot works, it works. But if we are in "Rule Mode", maybe we want to test Rulesvalue
        # Usually Glot is strictly better (cheaper/faster).
        
        try:
            src_d = GLOT_DIALECT_MAP.get(self.source_dialect, self.source_dialect)
            tgt_d = GLOT_DIALECT_MAP.get(self.target_dialect, self.target_dialect)
            # Transpile
            trans_sql = sqlglot.transpile(source_sql, read=src_d, write=tgt_d)[0]
            
            # Execute
            res_glot, err_glot = self.db_manager.execute_query(self.target_dialect, db_id, trans_sql)
            
            # Verify
            if res_glot is not None and check_result_same(res_glot, res_gt, check_order=check_order):
                with self.stats_lock:
                    self.stats['success_glot'] += 1
                    self.stats['total'] += 1
                return True, {
                    'translated_sql': trans_sql,
                    'annotation_source': 'glot'
                }
        except:
            pass # Glot failed, proceed to LLM

        # ==========================================
        # Strategy B: LLM with Reflection (Max 3 Retries)
        # ==========================================
        feedback_history = ""
        max_retries = 3
        
        current_rules = self.rules if use_rules else ""
        
        for attempt in range(max_retries):
            if self.stop_event.is_set(): break
            
            # Translate
            pred_sql = self.translator.translate(
                source_sql=source_sql,
                source_dialect=self.source_dialect,
                target_dialect=self.target_dialect,
                schema=schema,
                rules=current_rules,
                question=question,
                feedback_history=feedback_history
            )
            
            # Execute
            res_pred, err_pred = self.db_manager.execute_query(self.target_dialect, db_id, pred_sql)
            
            # Check Success
            is_exec_success = (res_pred is not None)
            is_match = False
            if is_exec_success:
                is_match = check_result_same(res_pred, res_gt, check_order=check_order)
            
            if is_match:
                # Determine tool label
                if use_rules:
                    tool_label = 'LLM-rule'
                    metric_key = 'success_llm_rule'
                elif attempt == 0:
                    tool_label = 'LLM-0shot'
                    metric_key = 'success_llm_0shot'
                else:
                    tool_label = 'LLM-retry'
                    metric_key = 'success_llm_retry'
                    
                with self.stats_lock:
                    self.stats[metric_key] += 1
                    self.stats['total'] += 1
                    
                return True, {
                    'translated_sql': pred_sql,
                    'annotation_source': tool_label
                }
            
            # Construct Feedback for next turn
            feedback = f"\n\n--- Retry {attempt+1} Feedback ---\n"
            feedback += f"Generated SQL: {pred_sql}\n"
            
            if not is_exec_success:
                feedback += f"Execution Error: {err_pred}\n"
                feedback += "Please fix the syntax error."
                
                # final_fail_log = f"ID {qid} [Exec Fail] {err_pred}"
                
            else:
                # Result Mismatch
                feedback += "Execution Status: Success, but Result Mismatch.\n"
                
                # Show top 5 rows for better context
                def format_top_n(obj, n=5):
                    if isinstance(obj, list):
                        sample = obj[:n]
                        suffix = f"... (Total Rows: {len(obj)})" if len(obj) > n else ""
                        return f"{str(sample)}{suffix}"
                    else:
                        s = str(obj)
                        return s[:300] + "..." if len(s) > 300 else s
                
                feedback += f"Expected Result (Top 5): {format_top_n(res_gt)}\n"
                feedback += f"Actual Result (Top 5): {format_top_n(res_pred)}\n"
                feedback += "Please correct the logic to match the expected result."
                
                # final_fail_log = f"ID {qid} [Mismatch]"
            
            feedback_history += feedback
        
        # Failed all retries
        with self.stats_lock:
            self.stats['failed'] += 1
            self.stats['total'] += 1
            
        return False, {
            'error': feedback_history,
            'translated_sql': pred_sql # Return last attempt
        }


