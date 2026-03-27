import sys, os
from dotenv import load_dotenv
load_dotenv("../.env")
sys.path.insert(0, os.path.abspath("."))
from app.utils.llm_client import LLMClient
from app.services.ontology_generator import ONTOLOGY_SYSTEM_PROMPT
client = LLMClient()
print("Model:", client.model)
try:
    messages = [
        {"role": "system", "content": ONTOLOGY_SYSTEM_PROMPT},
        {"role": "user", "content": "Analyze this text: 'The sales team needs a new director to handle operations.' Simulation focus: Corporate team reactions."}
    ]
    res = client.chat(messages=messages, response_format={"type": "json_object"})
    print("--- RAW OUTPUT ---")
    print(repr(res))
    import json
    json.loads(res)
    print("Valid JSON.")
except Exception as e:
    import traceback
    traceback.print_exc()
    print("Error:", str(e))
