import os
import json
from openai import OpenAI
from backend.app.core import config

def test_model(model_name):
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("Error: OPENAI_API_KEY not set")
        return

    client = OpenAI(api_key=api_key)
    print(f"Testing model: {model_name}...")
    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": "Return ONLY JSON: {\"status\": \"ok\"}"},
                {"role": "user", "content": "Ping"}
            ],
            response_format={"type": "json_object"}
        )
        print(f"Success! Response: {response.choices[0].message.content}")
    except Exception as e:
        print(f"FAILED: {e}")

if __name__ == "__main__":
    test_model(config.SOCIAL_LLM_MODEL)
