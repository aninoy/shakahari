import os
from dotenv import load_dotenv

# Load .env file for local development
load_dotenv()

# API Keys & Secrets
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
SHEET_CREDENTIALS = os.environ.get("G_SHEET_CREDENTIALS")
PERENUAL_API_KEY = os.environ.get("PERENUAL_API_KEY")

# Settings
MODEL_ID = "gemini-2.5-flash" 
LATITUDE = 34.05 
LONGITUDE = -118.25
SHEET_NAME = "ShakahariDB"
WORKSHEET_NAME = "Plants"