import json
from typing import Any

from langchain_core.tools import tool

from opensearch.client import OpenSearchClient

# Глобальный клиент OpenSearch (инициализируется при запуске)
_os_client: OpenSearchClient | None = None


def init_opensearch_client() -> OpenSearchClient:
    """Инициализация и подключение клиента OpenSearch."""
    global _os_client
    if _os_client is None:
        _os_client = OpenSearchClient()
        _os_client.connect()
    return _os_client


def get_opensearch_client() -> OpenSearchClient:
    """Получить текущий клиент OpenSearch."""
    global _os_client
    if _os_client is None:
        return init_opensearch_client()
    return _os_client


@tool
def search_clients_db(query: str) -> str:
    """Поиск во внутренней базе данных клиентов (OpenSearch).

    Используй для поиска информации о клиенте по названию компании,
    ИНН, отрасли или другим критериям. Возвращает карточки клиентов
    с историей взаимодействия, заметками, тегами и рейтингом.

    Args:
        query: Поисковый запрос — название компании, ИНН, отрасль или ключевое слово.

    Returns:
        JSON-строка с результатами поиска.
    """
    client = get_opensearch_client()
    results = client.search(query, size=5)

    if not results:
        return json.dumps(
            {"message": f"По запросу '{query}' ничего не найдено в базе клиентов"},
            ensure_ascii=False,
        )

    # Форматируем результаты для лучшего восприятия агентом
    formatted = []
    for r in results:
        item = {
            "company_name": r.get("company_name", ""),
            "inn": r.get("inn", ""),
            "industry": r.get("industry", ""),
            "okved": r.get("okved", ""),
            "okved_description": r.get("okved_description", ""),
            "description": r.get("description", ""),
            "website": r.get("website", ""),
            "region": r.get("region", ""),
            "employee_count": r.get("employee_count"),
            "tags": r.get("tags", []),
            "notes": r.get("notes", ""),
            "internal_rating": r.get("internal_rating"),
            "last_meeting_date": r.get("last_meeting_date", ""),
        }
        formatted.append(item)

    return json.dumps(formatted, ensure_ascii=False, indent=2)