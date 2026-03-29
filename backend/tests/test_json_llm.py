import sys, os
from dotenv import load_dotenv
load_dotenv("../.env")
sys.path.insert(0, os.path.abspath("."))
from app.utils.llm_client import LLMClient
client = LLMClient()
print("Model:", client.model)
try:
    res = client.chat(
        messages=[{"role": "system", "content": "You are a helpful assistant. Return ONLY valid JSON format with a test key."}],
        response_format={"type": "json_object"}
    )
    print("RAW RESPONSE:")
    print(repr(res))
except Exception as e:
    import traceback
    traceback.print_exc()
    print("Error:", str(e))
