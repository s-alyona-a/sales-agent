"""LLM-модуль для интеллектуального подбора продуктов клиентам.

Вместо простого маппинга по отрасли (targetIndustries),
использует GigaChat для анализа потребностей клиента
и подбора наиболее релевантных продуктов из каталога.

Возвращает структурированный JSON с ID продуктов,
оценкой релевантности и обоснованием рекомендации.

Если GigaChat недоступен — fallback на keyword-based matching.
"""

import json
import os
import re
import traceback
from pathlib import Path
from typing import Any
from rich.console import Console

import config


# ─── Загрузка каталога продуктов ──────────────────────────────────

_catalog_cache: list[dict] | None = None
console = Console()


def load_products_catalog() -> list[dict]:
    """Загрузка каталога продуктов из JSON-файла (с кешированием)."""
    global _catalog_cache
    if _catalog_cache is not None:
        return _catalog_cache

    catalog_path = Path(__file__).parent.parent / "crm" / "data" / "products_catalog.json"
    console.print(catalog_path)
    if not catalog_path.exists():
        console.print("NO CATALOG PATH")
        # Fallback: пробуем через директорию api_server
        catalog_path = Path(os.path.dirname(os.path.abspath(__file__))).parent / "crm" / "data" / "products_catalog.json.json"

    if catalog_path.exists():
        with open(catalog_path, "r", encoding="utf-8") as f:
            _catalog_cache = json.load(f)
            return _catalog_cache

    return []


def _build_catalog_summary(products: list[dict]) -> str:
    """Формирует компактное описание каталога для LLM-промпта."""
    lines = []
    for p in products:
        keywords = ", ".join(p.get("keywords", []))
        target = ", ".join(p.get("targetIndustries", p.get("target_industries", [])))
        lines.append(
            f"[{p.get('id', '?')}] {p.get('name', '')} ({p.get('category', '')}) — "
            f"{p.get('description', '')[:200]} | "
            f"Отрасли: {target} | "
            f"Ключевые слова: {keywords}"
        )
    return "\n".join(lines)


def _build_client_context(card_data: dict) -> str:
    """Извлекает ключевые данные о клиенте из карточки для промпта."""
    lines = []

    # CRM данные
    crm = card_data.get("crm", {})
    ci = crm.get("client_info") or crm.get("clientInfo") or {}
    if ci:
        if ci.get("industry"):
            lines.append(f"Отрасль: {ci['industry']}")
        if ci.get("description"):
            lines.append(f"Описание деятельности: {ci['description']}")
        if ci.get("status"):
            lines.append(f"Статус клиента: {ci['status']}")
        if ci.get("okved"):
            lines.append(f"ОКВЭД: {ci['okved']}")

    # OpenSearch
    os_list = card_data.get("opensearch", [])
    if os_list:
        os_data = os_list[0]
        if os_data.get("industry"):
            lines.append(f"Отрасль (из базы): {os_data['industry']}")
        if os_data.get("description"):
            lines.append(f"Описание (из базы): {os_data['description']}")
        if os_data.get("tags"):
            tags = os_data["tags"] if isinstance(os_data["tags"], list) else [os_data["tags"]]
            lines.append(f"Теги: {', '.join(str(t) for t in tags)}")
        if os_data.get("notes"):
            lines.append(f"Заметки: {os_data['notes']}")

    # Тема встречи
    topic = card_data.get("meeting_topic") or card_data.get("meetingTopic", "")
    if topic:
        lines.append(f"Тема встречи: {topic}")

    # Сделки — какие продукты уже использовали
    deals = crm.get("deals", [])
    if deals:
        all_products = set()
        for d in deals:
            for p in d.get("products", []):
                all_products.add(p)
        if all_products:
            lines.append(f"Продукты в существующих сделках: {', '.join(all_products)}")

    # Новости — ключевые события
    news = card_data.get("web_news") or card_data.get("webNews", [])
    if news:
        lines.append("Ключевые новости:")
        for n in news[:3]:
            lines.append(f"  - {n.get('title', '')}")

    # Вакансии — направления развития
    vacancies = card_data.get("vacancies", [])
    if vacancies:
        lines.append("Открытые вакансии:")
        for v in vacancies[:3]:
            lines.append(f"  - {v.get('title', '')}")

    # СБАР
    sbar = card_data.get("sbar", {})
    if sbar:
        if sbar.get("main_activity"):
            lines.append(f"Основной вид деятельности (СБАР): {sbar['main_activity']}")
        okveds = sbar.get("okved", [])
        if okveds:
            lines.append("ОКВЭД (СБАР): " + ", ".join(
                f"{o.get('code', '')}: {o.get('name', '')}" for o in okveds[:5]
            ))

    return "\n".join(lines) if lines else "Данные о клиенте отсутствуют."


# ─── LLM-based подбор продуктов ────────────────────────────────────

def match_products_with_llm(card_data: dict, company_name: str = "", meeting_topic: str = "") -> list[dict]:
    """Подбор продуктов с помощью GigaChat LLM.

    Анализирует данные о клиенте и возвращает список рекомендованных продуктов
    с оценкой релевантности и обоснованием.

    Args:
        card_data: Данные карточки клиента (внутренний формат, snake_case).
        company_name: Название компании.
        meeting_topic: Тема встречи.

    Returns:
        Список словарей с ключами:
        - productId: ID продукта из каталога
        - relevance: 'high' | 'medium' | 'low'
        - reason: текстовое обоснование рекомендации
    """
    if not config.GIGACHAT_API_KEY:
        return _match_products_by_keywords(card_data)

    try:
        from agent.agent import create_llm
        from agent.prompts import PRODUCT_MATCH_SYSTEM_PROMPT, PRODUCT_MATCH_HUMAN_TEMPLATE
        from langchain_core.messages import SystemMessage, HumanMessage

        products = load_products_catalog()
        if not products:
            return []

        catalog_summary = _build_catalog_summary(products)
        client_context = _build_client_context(card_data)

        llm = create_llm()
        human = PRODUCT_MATCH_HUMAN_TEMPLATE.format(
            company_name=company_name or card_data.get("company_name", ""),
            meeting_topic=meeting_topic or card_data.get("meeting_topic", ""),
            client_context=client_context,
            catalog=catalog_summary,
        )

        response = llm.invoke([
            SystemMessage(content=PRODUCT_MATCH_SYSTEM_PROMPT),
            HumanMessage(content=human),
        ])

        raw = response.content.strip()

        # Извлекаем JSON из ответа
        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0].strip()
        elif "```" in raw:
            raw = raw.split("```")[1].split("```")[0].strip()

        # Убираем возможные trailing commas
        raw = re.sub(r',\s*}', '}', raw)
        raw = re.sub(r',\s*]', ']', raw)

        recommendations = json.loads(raw)

        print(f"RECOMMENDATIONS: {recommendations}")

        if isinstance(recommendations, dict) and "recommendations" in recommendations:
            recommendations = recommendations["recommendations"]

        if not isinstance(recommendations, list):
            return []

        # Валидация структуры
        valid = []
        for rec in recommendations:
            if isinstance(rec, dict) and rec.get("productId"):
                valid.append({
                    "productId": rec["productId"],
                    "relevance": rec.get("relevance", "medium"),
                    "reason": rec.get("reason", ""),
                })

        return valid

    except Exception as e:
        print(f"⚠️ LLM product matching failed: {e}")
        if config.DEBUG if hasattr(config, 'DEBUG') else False:
            traceback.print_exc()
        # Fallback на keyword-based matching
        return _match_products_by_keywords(card_data)


# ─── Keyword-based fallback ────────────────────────────────────────

def _match_products_by_keywords(card_data: dict) -> list[dict]:
    """Подбор продуктов по ключевым словам (без LLM).

    Используется как fallback когда GigaChat недоступен.
    Сопоставляет данные клиента с keywords и targetIndustries продуктов.
    """
    products = load_products_catalog()
    if not products:
        return []

    # Собираем ключевые слова из данных клиента
    client_keywords = set()
    client_industries = set()

    crm = card_data.get("crm", {})
    ci = crm.get("client_info") or crm.get("clientInfo") or {}
    if ci:
        if ci.get("industry"):
            client_industries.add(ci["industry"])
        if ci.get("description"):
            for word in ci["description"].lower().split():
                if len(word) > 4:
                    client_keywords.add(word)

    os_list = card_data.get("opensearch", [])
    if os_list:
        os_data = os_list[0]
        if os_data.get("industry"):
            client_industries.add(os_data["industry"])
        if os_data.get("description"):
            for word in os_data["description"].lower().split():
                if len(word) > 4:
                    client_keywords.add(word)
        if os_data.get("tags"):
            tags = os_data["tags"] if isinstance(os_data["tags"], list) else [os_data["tags"]]
            for t in tags:
                client_keywords.add(str(t).lower())

    # Тема встречи
    topic = card_data.get("meeting_topic") or card_data.get("meetingTopic", "")
    if topic:
        for word in topic.lower().split():
            if len(word) > 4:
                client_keywords.add(word)

    # Новости
    news = card_data.get("web_news") or card_data.get("webNews", [])
    for n in news[:3]:
        title = n.get("title", "").lower()
        for word in title.split():
            if len(word) > 4:
                client_keywords.add(word)

    # СБАР
    sbar = card_data.get("sbar", {})
    if sbar:
        okveds = sbar.get("okved", [])
        for o in okveds[:3]:
            name = o.get("name", "").lower()
            for word in name.split():
                if len(word) > 4:
                    client_keywords.add(word)

    # Мэтчим продукты
    recommendations = []
    for product in products:
        score = 0
        p_industries = set(
            product.get("targetIndustries", product.get("target_industries", []))
        )
        p_keywords = set(kw.lower() for kw in product.get("keywords", []))

        # Совпадение по отрасли
        industry_match = client_industries & p_industries
        score += len(industry_match) * 3

        # Совпадение по ключевым словам
        keyword_match = client_keywords & p_keywords
        score += len(keyword_match) * 2

        # Совпадение названия продукта с описанием клиента
        p_desc = product.get("description", "").lower()
        for kw in client_keywords:
            if kw in p_desc:
                score += 1

        if score > 0:
            relevance = "high" if score >= 6 else "medium" if score >= 3 else "low"
            reason_parts = []
            if industry_match:
                reason_parts.append(f"Отрасль клиента: {', '.join(industry_match)}")
            if keyword_match:
                reason_parts.append(f"Совпадение по ключевым словам: {', '.join(list(keyword_match)[:5])}")

            recommendations.append({
                "productId": product["id"],
                "relevance": relevance,
                "reason": "; ".join(reason_parts) if reason_parts else "Частичное совпадение по описанию",
            })

    # Сортируем по релевантности
    relevance_order = {"high": 0, "medium": 1, "low": 2}
    recommendations.sort(key=lambda r: relevance_order.get(r["relevance"], 3))

    return recommendations


# ─── Обогащение продуктов рекомендациями ───────────────────────────

def enrich_products_with_recommendations(
    products: list[dict],
    card_data: dict,
    company_name: str = "",
    meeting_topic: str = "",
) -> list[dict]:
    """Добавляет поля recommended и recommendationReason к продуктам.

    Вызывает LLM для подбора продуктов и обогащает исходный список продуктов
    флагами рекомендации.

    Args:
        products: Исходный список продуктов из каталога.
        card_data: Данные карточки клиента (snake_case).
        company_name: Название компании.
        meeting_topic: Тема встречи.

    Returns:
        Обогащённый список продуктов с полями:
        - recommended: bool
        - recommendationReason: str
        - relevance: 'high' | 'medium' | 'low' (только для recommended)
    """
    if not products:
        return products

    # Получаем рекомендации
    recommendations = match_products_with_llm(card_data, company_name, meeting_topic)

    # Создаём маппинг productId → рекомендация
    rec_map = {}
    for rec in recommendations:
        rec_map[rec["productId"]] = rec

    # Обогащаем каждый продукт
    enriched = []
    products = load_products_catalog()
    for product in products:
        p = dict(product)  # копируем
        product_id = p.get("id", "")
        rec = rec_map.get(product_id)

        if rec:
            p["recommended"] = True
            p["recommendationReason"] = rec.get("reason", "")
            p["relevance"] = rec.get("relevance", "medium")
        else:
            p["recommended"] = False
            p["recommendationReason"] = ""
            p["relevance"] = ""

        enriched.append(p)

    # Сортируем: recommended сначала, потом по relevance
    relevance_order = {"high": 0, "medium": 1, "low": 2, "": 3}
    enriched.sort(key=lambda p: (0 if p.get("recommended") else 1, relevance_order.get(p.get("relevance", ""), 3)))

    return enriched