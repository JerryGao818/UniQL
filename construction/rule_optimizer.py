import os
import time
import requests
import json
from config import OPTIMIZER_CONFIG

class RuleOptimizer:
    def __init__(self, rules_dir='./rules'):
        self.rules_dir = rules_dir
        if not os.path.exists(rules_dir):
            os.makedirs(rules_dir)
            
        with open('./prompts/optimization_template.txt', 'r', encoding='utf-8') as f:
            self.template = f.read()

        # Token Usage Stats
        self.token_usage = {'prompt': 0, 'completion': 0, 'total': 0}

    def get_rules_path(self, source_dialect, target_dialect):
        return os.path.join(self.rules_dir, f"rules_{source_dialect}_{target_dialect}.txt")

    def load_rules(self, source_dialect, target_dialect):
        path = self.get_rules_path(source_dialect, target_dialect)
        # print(f"Loading rules from: {path}")
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                return f.read()
        return "No specific rules yet."

    def save_rules(self, source_dialect, target_dialect, rules_content):
        path = self.get_rules_path(source_dialect, target_dialect)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(rules_content)
        print(f"Updated rules saved to {path}")

    def optimize(self, source_dialect, target_dialect, error_logs, schema_info=""):
        """
        Analyze logs and generate new rules.
        """
        if not error_logs:
            print("No error logs to optimize.")
            return

        print(f"Optimizing rules for {source_dialect} -> {target_dialect} based on {len(error_logs)} errors...")
        
        # Format logs for Prompt
        # Limit context window usage if too many errors
        logs_str = "\n".join(error_logs[:50]) 
        
        prompt = self.template.format(
            source_dialect=source_dialect,
            target_dialect=target_dialect,
            schema=schema_info,
            error_logs=logs_str
        )
        
        new_rules = self._call_llm_optimizer(prompt)
        
        # Append logic
        current_rules = self.load_rules(source_dialect, target_dialect)
        if "No specific rules yet" in current_rules:
            updated_rules_content = new_rules
        else:
            updated_rules_content = current_rules + "\n\n" + f"--- Update {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n" + new_rules
            
        self.save_rules(source_dialect, target_dialect, updated_rules_content)

    def _call_llm_optimizer(self, prompt):
        """
        Call Gemini 3 Pro API (OpenKey) for rule optimization.
        """
        model_name = OPTIMIZER_CONFIG.get('model', 'gemini-2.5-pro')
        
        url = OPTIMIZER_CONFIG['url']
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f"Bearer {OPTIMIZER_CONFIG['api_key']}"
        }
        data = {
            "model": model_name,
            "messages": [{"role": "user", "content": prompt}]
        }

        try:
            response = requests.post(url, headers=headers, json=data)
            if response.status_code == 200:
                res_json = response.json()
                content = res_json['choices'][0]['message']['content']
                
                # Track usage
                usage = res_json.get('usage', {})
                p_tokens = usage.get('prompt_tokens', 0)
                c_tokens = usage.get('completion_tokens', 0)
                t_tokens = usage.get('total_tokens', 0)
                
                self.token_usage['prompt'] += p_tokens
                self.token_usage['completion'] += c_tokens
                self.token_usage['total'] += t_tokens
                
                return content
            else:
                print(f"API Error: Status {response.status_code}, Response: {response.text}")
                return "Error in automatic optimization."
        except Exception as e:
            print(f"Request Error: {e}")
            return f"Exception during optimization: {e}"


