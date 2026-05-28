"""MCP-сервер для CRM — обёртка над CRM-движком.

Позволяет подключать CRM как MCP-инструмент для любых агентов,
поддерживающих протокол MCP (Model Context Protocol).

Запуск:
    python -m crm.mcp_server

Для подключения реальной CRM замените MockCRM на свою реализацию
и укажите CRM_TYPE=mcp в .env.
"""

import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from .mock_crm import MockCRM

# Создание MCP-сервера
mcp = FastMCP(
    "Sales CRM",
    instructions="CRM-система для агента-помощника менеджера по продажам. Позволяет искать клиентов, получать сделки, контакты и историю взаимодействий.",
)

# Инициализация CRM-движка
crm = MockCRM()


@mcp.tool()
def search_clients(query: str) -> str:
    """Поиск клиентов по названию компании или ИНН.

    Args:
        query: Поисковый запрос — название компании или ИНН.

    Returns:
        JSON-строка со списком найденных клиентов.
    """
    results = crm.search_clients(query)
    return json.dumps(results, ensure_ascii=False, indent=2)


@mcp.tool()
def get_client_info(company_name: str) -> str:
    """Получить карточку клиента по названию компании.

    Args:
        company_name: Название компании (точное или частичное совпадение).

    Returns:
        JSON-строка с информацией о клиенте или 'null', если не найден.
    """
    result = crm.get_client_info(company_name)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def get_client_deals(client_id: str) -> str:
    """Получить список сделок клиента по его ID в CRM.

    Args:
        client_id: Идентификатор клиента в CRM (например, CL-001).

    Returns:
        JSON-строка со списком сделок.
    """
    results = crm.get_deals(client_id)
    return json.dumps(results, ensure_ascii=False, indent=2)


@mcp.tool()
def get_client_contacts(client_id: str) -> str:
    """Получить список контактных лиц клиента по его ID в CRM.

    Args:
        client_id: Идентификатор клиента в CRM (например, CL-001).

    Returns:
        JSON-строка со списком контактов. ЛПР отмечены полем is_lpr=true.
    """
    results = crm.get_contacts(client_id)
    return json.dumps(results, ensure_ascii=False, indent=2)


@mcp.tool()
def get_interaction_history(client_id: str) -> str:
    """Получить историю взаимодействий с клиентом по его ID в CRM.

    Args:
        client_id: Идентификатор клиента в CRM (например, CL-001).

    Returns:
        JSON-строка с историей взаимодействий (звонки, встречи, письма, задачи).
    """
    results = crm.get_interaction_history(client_id)
    return json.dumps(results, ensure_ascii=False, indent=2)


@mcp.tool()
def get_our_products() -> str:
    """Получить каталог наших продуктов и услуг.

    Returns:
        JSON-строка со списком продуктов, включая категории и целевые отрасли.
    """
    results = crm.get_our_products()
    return json.dumps(results, ensure_ascii=False, indent=2)


@mcp.resource("crm://clients/{client_id}")
def get_client_resource(client_id: str) -> str:
    """Ресурс MCP — полная информация о клиенте (карточка + сделки + контакты)."""
    client = None
    for c in crm._data.get("clients", []):
        if c["id"] == client_id:
            client = c
            break

    if client is None:
        return json.dumps({"error": f"Клиент {client_id} не найден"}, ensure_ascii=False)

    full_info = {
        "client": client,
        "deals": crm.get_deals(client_id),
        "contacts": crm.get_contacts(client_id),
        "interactions": crm.get_interaction_history(client_id),
    }
    return json.dumps(full_info, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    mcp.run(transport="stdio")
