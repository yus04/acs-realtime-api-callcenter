import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Azure Communication Services configuration
ACS_CONNECTION_STRING = os.getenv("ACS_CONNECTION_STRING")
CALLBACK_URI_HOST = os.getenv("CALLBACK_URI_HOST")
CALLBACK_EVENTS_URI = f"{CALLBACK_URI_HOST}/api/callbacks"

# Azure OpenAI service configuration
AZURE_OPENAI_SERVICE_ENDPOINT = os.getenv("AZURE_OPENAI_SERVICE_ENDPOINT")
AZURE_OPENAI_SERVICE_KEY = os.getenv("AZURE_OPENAI_SERVICE_KEY")
AZURE_OPENAI_DEPLOYMENT_NAME = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")
