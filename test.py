# list_models.py
import os
from google import genai

# Make sure your env var is set: export GEMINI_API_KEY="your_key"
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

print("🔍 Searching for available models...")
try:
    # This lists all models available to your API key
    for model in client.models.list():
        # We only care about models that support content generation
        if "generateContent" in model.supported_actions:
            print(f"- {model.name}")
except Exception as e:
    print(f"❌ Error: {e}")