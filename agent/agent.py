"""Основной модуль агента на LangChain + GigaChat.

Два режима работы:
1. ReAct-агент через LangGraph (create_agent / run_agent) — GigaChat сам вызывает инструменты.
   МИНУС: GigaChat не всегда надёжно вызывает инструменты.
2. Программный пайплайн (run_pipeline) — детерминированный сбор данных + LLM-анализ.
   ПЛЮС: гарантированно опрашивает все источники.

API Server использует вариант 2 (pipeline) по умолчанию.
"""

from langchain_gigachat.chat_models import GigaChat
from langchain_core.messages import SystemMessage, HumanMessage

from agent.pipeline import collect_data, ClientData
from agent.prompts import ANALYSIS_SYSTEM_PROMPT, ANALYSIS_HUMAN_TEMPLATE

import config


def create_llm() -> GigaChat:
    """Создание экземпляра GigaChat LLM.

    Raises:
        ValueError: Если учётные данные GigaChat не заданы.
    """
    if not config.GIGACHAT_API_KEY:
        raise ValueError(
            "Учётные данные GigaChat не заданы!\n"
            "Укажите GIGACHAT_API_KEY в файле .env\n"
            "Получить credentials: https://developers.sber.ru/"
        )

    llm = GigaChat(
        credentials=config.GIGACHAT_API_KEY,
        scope=config.GIGACHAT_SCOPE,
        model=config.GIGACHAT_MODEL,
        profanity_check=False,
        verify_ssl_certs=False,
        temperature=0.3,
        max_tokens=8000,
        timeout=180,
        retry=True,
    )
    return llm


def run_pipeline(company_name: str, meeting_topic: str, inn: str = "") -> dict:
    """Программный пайплайн: сбор данных + LLM-анализ.

    Двухфазный процесс:
    1. Сбор данных: программно опрашивает все источники (CRM, OpenSearch, WebSearch)
    2. Анализ: GigaChat генерирует карточку на основе собранных данных

    Args:
        company_name: Название компании.
        meeting_topic: Тема предстоящей встречи.
        inn: ИНН компании (опционально, для INN-priority поиска).

    Returns:
        dict с ключами: 'analysis' (markdown), 'raw_data' (ClientData), 'errors' (list)
    """
    # === Фаза 1: Сбор данных ===
    print(f"\n📡 Фаза 1: Сбор данных для «{company_name}»...")
    if inn:
        print(f"   INN-priority: ИНН={inn}")

    data = collect_data(company_name, meeting_topic, inn)

    # Собираем статистику
    os_count = len(data.os_results)
    crm_found = data.crm_client_info is not None
    deals_count = len(data.crm_deals)
    contacts_count = len(data.crm_contacts)
    news_count = len(data.web_news)
    leaders_count = len(data.web_leaders)
    vacancies_count = len(data.web_vacancies)

    print(f"\n📊 Собрано данных:")
    print(f"   OpenSearch: {os_count} записей")
    print(f"   CRM: {'найден' if crm_found else 'не найден'} | Сделок: {deals_count} | Контактов: {contacts_count}")
    print(f"   Новости: {news_count} | Руководство: {leaders_count} | Вакансии: {vacancies_count}")

    if data.errors:
        print(f"   ⚠️ Ошибки: {len(data.errors)}")
        for e in data.errors:
            print(f"      - {e[:100]}")

    # === Фаза 2: LLM-анализ ===
    print(f"\n🤖 Фаза 2: Анализ данных и генерация карточки (GigaChat)...")

    llm = create_llm()

    # Формируем контекст из собранных данных
    context = data.to_context_string()

    # Формируем промпт
    inn_text = f"\n**ИНН:** {inn}" if inn else ""
    system_msg = SystemMessage(content=ANALYSIS_SYSTEM_PROMPT)
    human_msg = HumanMessage(content=ANALYSIS_HUMAN_TEMPLATE.format(
        company_name=company_name,
        meeting_topic=meeting_topic,
        collected_data=context,
        inn_text=inn_text,
    ))

    # Вызываем GigaChat
    response = llm.invoke([system_msg, human_msg])

    return {
        "analysis": response.content,
        "raw_data": data.to_context_string(),
        "client_data": data,
        "errors": data.errors,
    }


# не используется в api_server.py

def create_agent():
    """Создание ReAct-агента через LangGraph.

    ВНИМАНИЕ: GigaChat не всегда надёжно вызывает инструменты.
    Рекомендуется использовать run_pipeline() вместо этого метода.

    Returns:
        CompiledStateGraph — скомпилированный граф агента.
    """
    from langgraph.prebuilt import create_react_agent
    from agent.prompts import SYSTEM_PROMPT
    from agent.tools.opensearch_tool import (
        search_clients_db,
        init_opensearch_client,
    )
    from agent.tools.crm_tool import (
        crm_get_client_info,
        crm_search_clients,
        crm_get_deals,
        crm_get_contacts,
        crm_get_interactions,
        crm_get_our_products,
        init_crm,
    )
    from agent.tools.websearch_tool import (
        web_search,
        web_search_news,
        read_web_page,
        search_company_vacancies,
        search_company_leaders,
        search_company_inn,
    )
    from agent.tools.sbar_tool import sbar_search_by_inn

    all_tools = [
        search_clients_db,
        crm_get_client_info, crm_search_clients, crm_get_deals,
        crm_get_contacts, crm_get_interactions, crm_get_our_products,
        web_search, web_search_news, read_web_page,
        search_company_vacancies, search_company_leaders, search_company_inn,
        sbar_search_by_inn
    ]

    # Инициализация ресурсов
    print("📡 Подключение к OpenSearch...")
    init_opensearch_client()

    print("📡 Инициализация CRM...")
    init_crm()

    # Создание LLM
    print("🤖 Подключение к GigaChat...")
    llm = create_llm()
    print(f"   Модель: {config.GIGACHAT_MODEL}")

    # Создание агента через LangGraph
    agent = create_react_agent(
        model=llm,
        tools=all_tools,
        prompt=SYSTEM_PROMPT,
    )

    return agent


def run_agent(company_name: str, meeting_topic: str, inn: str="") -> str:
    """Запуск ReAct-агента (устаревший, используйте run_pipeline).

    Args:
        company_name: Название компании.
        meeting_topic: Тема предстоящей встречи.

    Returns:
        Сформированная карточка клиента в формате Markdown.
    """
    from agent.prompts import HUMAN_PROMPT_TEMPLATE

    agent = create_agent()

    input_message = HUMAN_PROMPT_TEMPLATE.format(
        company_name=company_name,
        meeting_topic=meeting_topic,
        inn=inn,
    )

    result = agent.invoke(
        {"messages": [HumanMessage(content=input_message)]},
    )

    messages = result.get("messages", [])
    if messages:
        return messages[-1].content

    return "Ошибка: агент не вернул результат"