import os
from pathlib import Path
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

# === Пути ===
BASE_DIR = Path(__file__).parent
CRM_DATA_DIR = BASE_DIR / "crm" / "data"
OPENSEARCH_DATA_DIR = BASE_DIR / "opensearch" / "data"

# === GigaChat ===
GIGACHAT_API_KEY = os.getenv("GIGACHAT_API_KEY", "")
GIGACHAT_SCOPE = os.getenv("GIGACHAT_SCOPE", "GIGACHAT_API_CORP")
GIGACHAT_MODEL = os.getenv("GIGACHAT_MODEL", "GigaChat-Pro")

# === OpenSearch ===
OPENSEARCH_HOST = os.getenv("OPENSEARCH_HOST", "localhost")
OPENSEARCH_PORT = int(os.getenv("OPENSEARCH_PORT", "9200"))
OPENSEARCH_USER = os.getenv("OPENSEARCH_USER", "admin")
OPENSEARCH_PASSWORD = os.getenv("OPENSEARCH_PASSWORD", "admin")
OPENSEARCH_USE_SSL = os.getenv("OPENSEARCH_USE_SSL", "true").lower() == "true"
OPENSEARCH_VERIFY_CERTS = os.getenv("OPENSEARCH_VERIFY_CERTS", "false").lower() == "true"
OPENSEARCH_INDEX = "lf-clients"

# === CRM ===
CRM_TYPE = os.getenv("CRM_TYPE", "mock")
CRM_MCP_URL = os.getenv("CRM_MCP_URL", "")
CRM_API_URL = os.getenv("CRM_API_URL", "")
CRM_API_KEY = os.getenv("CRM_API_KEY", "")

# === Web Search ===
DDGS_PROXY = os.getenv("DDGS_PROXY", "")
WEB_READ_TIMEOUT = int(os.getenv("WEB_READ_TIMEOUT", "30"))
MAX_PAGES_TO_READ = int(os.getenv("MAX_PAGES_TO_READ", "5"))