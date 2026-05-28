import json
from typing import Any

from langchain_core.tools import tool

from crm.base import CRMBase
from crm.mock_crm import MockCRM

import config

# Глобальный экземпляр CRM (инициализируется при запуске)
_crm: CRMBase | None = None


def init_crm() -> CRMBase:
    """Инициализация CRM-движка в зависимости от конфигурации."""
    global _crm
    if _crm is None:
        crm_type = config.CRM_TYPE.lower()
        if crm_type == "mock":
            _crm = MockCRM()
        elif crm_type == "api":
            # TODO: Реализовать ApiCRM при подключении реальной CRM
            raise NotImplementedError("API CRM пока не реализована. Используйте CRM_TYPE=mock")
        elif crm_type == "mcp":
            # TODO: Реализовать McpCRM для подключения к MCP-серверу CRM
            raise NotImplementedError("MCP CRM пока не реализована. Используйте CRM_TYPE=mock")
        else:
            raise ValueError(f"Неизвестный тип CRM: {crm_type}")
    return _crm


def get_crm() -> CRMBase:
    """Получить текущий экземпляр CRM."""
    global _crm
    if _crm is None:
        return init_crm()
    return _crm


@tool
def crm_get_client_info(company_name: str) -> str:
    """Получить карточку клиента из CRM по названию компании.

    Возвращает базовую информацию о клиенте: название, ИНН, сайт,
    отрасль, статус. Для получения сделок и контактов используй
    отдельные инструменты с client_id.

    Args:
        company_name: Название компании (точное или частичное совпадение).

    Returns:
        JSON-строка с информацией о клиенте.
    """
    crm = get_crm()
    result = crm.get_client_info(company_name)

    if result is None:
        return json.dumps(
            {"message": f"Клиент '{company_name}' не найден в CRM"},
            ensure_ascii=False,
        )

    return json.dumps(result, ensure_ascii=False, indent=2)

@tool
def crm_get_client_by_inn(inn: str) -> str:
    """Получить карточку клиента из CRM по ИНН.

    Используй для точного поиска клиента, если известен ИНН.
    ИНН даёт точное совпадение, в отличие от названия компании.

    Args:
        inn: ИНН компании (10 или 12 цифр).

    Returns:
        JSON-строка с информацией о клиенте.
    """
    crm = get_crm()
    result = crm.get_client_by_inn(inn)

    if result is None:
        return json.dumps(
            {"message": f"Клиент с ИНН '{inn}' не найден в CRM"},
            ensure_ascii=False,
        )

    return json.dumps(result, ensure_ascii=False, indent=2)

@tool
def crm_search_clients(query: str) -> str:
    """Поиск клиентов в CRM по названию или ИНН.

    Используй, если точное название компании неизвестно или
    нужно найти все компании с похожим названием.

    Args:
        query: Поисковый запрос — часть названия компании или ИНН.

    Returns:
        JSON-строка со списком найденных клиентов (упрощённые карточки).
    """
    crm = get_crm()
    results = crm.search_clients(query)

    if not results:
        return json.dumps(
            {"message": f"По запросу '{query}' клиенты в CRM не найдены"},
            ensure_ascii=False,
        )

    return json.dumps(results, ensure_ascii=False, indent=2)


@tool
def crm_get_deals(client_id: str) -> str:
    """Получить список сделок клиента из CRM.

    Показывает историю всех сделок: закрытые, текущие, проигранные.
    Включает суммы, продукты и даты.

    Args:
        client_id: Идентификатор клиента в CRM (например, CL-001).

    Returns:
        JSON-строка со списком сделок.
    """
    crm = get_crm()
    results = crm.get_deals(client_id)

    if not results:
        return json.dumps(
            {"message": f"Сделки для клиента {client_id} не найдены"},
            ensure_ascii=False,
        )

    return json.dumps(results, ensure_ascii=False, indent=2)


@tool
def crm_get_contacts(client_id: str) -> str:
    """Получить список контактных лиц клиента из CRM.

    Показывает всех контактов с указанием должности, является ли
    контакт ЛПР (лицом, принимающим решения), и заметками.

    Args:
        client_id: Идентификатор клиента в CRM (например, CL-001).

    Returns:
        JSON-строка со списком контактов.
    """
    crm = get_crm()
    results = crm.get_contacts(client_id)

    if not results:
        return json.dumps(
            {"message": f"Контакты для клиента {client_id} не найдены"},
            ensure_ascii=False,
        )

    return json.dumps(results, ensure_ascii=False, indent=2)


@tool
def crm_get_interactions(client_id: str) -> str:
    """Получить историю взаимодействий с клиентом из CRM.

    Показывает все звонки, встречи, письма и задачи по клиенту.
    Включает описание и итог каждого взаимодействия.

    Args:
        client_id: Идентификатор клиента в CRM (например, CL-001).

    Returns:
        JSON-строка с историей взаимодействий.
    """
    crm = get_crm()
    results = crm.get_interaction_history(client_id)

    if not results:
        return json.dumps(
            {"message": f"История взаимодействий для клиента {client_id} не найдена"},
            ensure_ascii=False,
        )

    return json.dumps(results, ensure_ascii=False, indent=2)


@tool
def crm_get_our_products() -> str:
    """Получить каталог наших продуктов и услуг.

    Используй для анализа того, какие продукты мы можем предложить
    клиенту на основе его отрасли и потребностей. Каждый продукт
    содержит список целевых отраслей.

    Returns:
        JSON-строка со списком продуктов.
    """
    crm = get_crm()
    results = crm.get_our_products()
    return json.dumps(results, ensure_ascii=False, indent=2)