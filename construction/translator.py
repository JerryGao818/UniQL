from openai import AzureOpenAI
from config import AZURE_OPENAI_CONFIG
from utils import clean_llm_sql
import tiktoken
import threading
import re

class SQLTranslator:
    def __init__(self):
        # Handle endpoint cleaning
        endpoint = AZURE_OPENAI_CONFIG['azure_endpoint']
        # If it contains /openai/, strip it for the standard SDK which appends it automatically
        match = re.match(r"(https://[^/]+)", endpoint)
        if match:
            base_endpoint = match.group(1)
        else:
            base_endpoint = endpoint

        self.client = AzureOpenAI(
            api_key=AZURE_OPENAI_CONFIG['api_key'],
            azure_endpoint=base_endpoint,
            api_version=AZURE_OPENAI_CONFIG['api_version']
        )
        # Load template
        with open('./prompts/translate_template.txt', 'r', encoding='utf-8') as f:
            self.template = f.read()
            
        # Token Counting
        try:
            self.encoding = tiktoken.get_encoding("cl100k_base")
        except:
            self.encoding = None
            
        self.token_stats = {'prompt': 0, 'completion': 0, 'total': 0}
        self.stats_lock = threading.Lock()

    def translate(self, source_sql, source_dialect, target_dialect, schema, rules, question="", feedback_history=""):
        """
        Translate SQL using LLM.
        """
        base_prompt = self.template.format(
            source_dialect=source_dialect,
            target_dialect=target_dialect,
            question=question,
            schema=schema,
            source_sql=source_sql,
            specific_rules=rules
        )

        full_prompt = base_prompt + feedback_history
        
        # Count prompt tokens
        p_tokens = 0
        if self.encoding:
            try:
                p_tokens = len(self.encoding.encode(full_prompt))
            except: pass
        
        try:
                # Using specific API call format as requested
                response = self.client.responses.create(model='gpt-5-mini', input=full_prompt)
                text = response.output_text
                
                # Count completion tokens
                c_tokens = 0
                if self.encoding and text:
                    try:
                        c_tokens = len(self.encoding.encode(text))
                    except: pass
                
                with self.stats_lock:
                    self.token_stats['prompt'] += p_tokens
                    self.token_stats['completion'] += c_tokens
                    self.token_stats['total'] += (p_tokens + c_tokens)
                
                return clean_llm_sql(text)
                
        except KeyboardInterrupt:
            print("\n[Translator] Interrupted by user.")
            raise

        except AttributeError:
             # Fallback logic matching reference
             try:
                response = self.client.responses.create(model='gpt-5-mini', input=full_prompt)
                text = response.output_text
                
                c_tokens = 0
                if self.encoding and text:
                     try: c_tokens = len(self.encoding.encode(text))
                     except: pass
                
                with self.stats_lock:
                    self.token_stats['prompt'] += p_tokens
                    self.token_stats['completion'] += c_tokens
                    self.token_stats['total'] += (p_tokens + c_tokens)

                return clean_llm_sql(text)
             except KeyboardInterrupt:
                 raise
             except Exception as e:
                print(f"Translation API Error (Fallback): {e}")
                return f"Error: {e}"
        except Exception as e:
            print(f"Translation API Error: {e}")
            return f"Error: {e}"


