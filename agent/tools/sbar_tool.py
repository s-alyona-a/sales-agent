import json
from typing import Any

import requests
from langchain_core.tools import tool


# ─── Константы СБАР API ─────────────────────────────────────────

SBAR_SEARCH_URL = "https://api.sbar.sberanalytics.ru/search"
SBAR_COLLECTOR_URL = "https://api.sbar.sberanalytics.ru/collector"
SBAR_HEADERS = {"Content-Type": "application/json"}
SBAR_DEFAULT_PAYLOAD = {
    "pagination": {
        "limit": 100,
        "page": 1,
    }
}


# ─── Внутренние функции ─────────────────────────────────────────

def _search_by_inn(inn: str) -> dict[str, str]:
    """Поиск компании в СБАР по ИНН. Возвращает базовую информацию.

    Args:
        inn: ИНН компании (10 или 12 цифр).

    Returns:
        dict с ключами: ogrn, full_name, main_activity, main_activity_code.
        Пустые строки, если данные не найдены.
    """
    payload = {
        "text": inn,
        "pagination": {"page": 1, "limit": 5},
    }

    try:
        response = requests.post(SBAR_SEARCH_URL, json=payload, timeout=15)
        response.raise_for_status()

        items = response.json().get("items", [])
        if not items:
            return {"ogrn": "", "full_name": "", "main_activity": "", "main_activity_code": ""}

        item = items[0]
        return {
            "ogrn": item.get("ogrn", ""),
            "full_name": item.get("full_name", ""),
            "main_activity": item.get("activity_main_name", ""),
            "main_activity_code": item.get("activity_main_code", ""),
        }

    except Exception as e:
        print(f"⚠ СБАР search_by_inn ошибка: {e}")
        return {"ogrn": "", "full_name": "", "main_activity": "", "main_activity_code": ""}


def _get_okveds(ogrn: str) -> list[dict[str, str]]:
    """Получение ОКВЭД компании по ОГРН.

    Args:
        ogrn: ОГРН компании.

    Returns:
        Список dict с ключами: code, name.
    """
    if not ogrn:
        return []

    url = f"{SBAR_COLLECTOR_URL}/company/{ogrn}/activity"
    try:
        response = requests.post(url, json=SBAR_DEFAULT_PAYLOAD, headers=SBAR_HEADERS, timeout=15)
        response.raise_for_status()

        data = response.json().get("data", [])
        return [{"code": act.get("code", ""), "name": act.get("fullname", "")} for act in data]

    except Exception as e:
        print(f"⚠ СБАР get_okveds ошибка: {e}")
        return []


def _get_participants(ogrn: str) -> list[dict[str, str]]:
    """Получение учредителей и руководства по ОГРН.

    Args:
        ogrn: ОГРН компании.

    Returns:
        Список dict с ключами: role, name.
    """
    if not ogrn:
        return []

    url = f"{SBAR_COLLECTOR_URL}/company/{ogrn}/participants"
    try:
        response = requests.post(url, json=SBAR_DEFAULT_PAYLOAD, headers=SBAR_HEADERS, timeout=15)
        response.raise_for_status()

        data = response.json().get("data", [])
        return [{"role": p.get("role", ""), "name": p.get("name", "")} for p in data]

    except Exception as e:
        print(f"⚠ СБАР get_participants ошибка: {e}")
        return []


def _get_egrul(ogrn: str) -> list[dict[str, str]]:
    """Получение записей ЕГРЮЛ по ОГРН.

    Args:
        ogrn: ОГРН компании.

    Returns:
        Список dict с ключами: name, register_date.
    """
    if not ogrn:
        return []

    url = f"{SBAR_COLLECTOR_URL}/company/{ogrn}/egrul"
    try:
        response = requests.post(url, json=SBAR_DEFAULT_PAYLOAD, headers=SBAR_HEADERS, timeout=15)
        response.raise_for_status()

        data = response.json().get("data", [])
        return [{"name": n.get("name", ""), "register_date": n.get("register_date", "")} for n in data]

    except Exception as e:
        print(f"⚠ СБАР get_egrul ошибка: {e}")
        return []


# ─── Основная функция ───────────────────────────────────────────

def get_company_info(inn: str) -> dict[str, Any]:
    """Получение полной информации о компании из СБАР по ИНН.

    Возвращает:
    - ogrn, full_name, main_activity, main_activity_code — из поиска по ИНН
    - okved — список ОКВЭД
    - participants — учредители и руководство
    - egrul — записи ЕГРЮЛ

    Args:
        inn: ИНН компании.

    Returns:
        dict со всей информацией или пустой dict при ошибке.
    """
    if not inn:
        return {}

    inn = str(inn).strip()

    # Шаг 1: Поиск по ИНН — получаем ОГРН и базовую информацию
    search_result = _search_by_inn(inn)
    ogrn = search_result.get("ogrn", "")

    result: dict[str, Any] = {
        "inn": inn,
        "ogrn": ogrn,
        "full_name": search_result.get("full_name", ""),
        "main_activity": search_result.get("main_activity", ""),
        "main_activity_code": search_result.get("main_activity_code", ""),
        "okved": [],
        "participants": [],
        "egrul": [],
    }

    if not ogrn:
        print(f"⚠ СБАР: ОГРН не найден для ИНН {inn}")
        return result

    # Шаг 2: Получаем детали по ОГРН
    okveds = _get_okveds(ogrn)
    participants = _get_participants(ogrn)
    egrul = _get_egrul(ogrn)

    if okveds:
        result["okved"] = okveds
    if participants:
        result["participants"] = participants
    if egrul:
        result["egrul"] = egrul

    return result


# ─── LangChain-инструмент ──────────────────────────────────────

@tool
def sbar_search_by_inn(inn: str) -> str:
    """Поиск информации о компании по ИНН через СБАР (Sber Analytics).

    Возвращает юридическую информацию: ОГРН, полное название, ОКВЭД,
    учредителей, руководство и записи ЕГРЮЛ. Используй этот инструмент
    когда известен ИНН компании для получения точных юридических данных.

    Args:
        inn: ИНН компании (10 или 12 цифр).

    Returns:
        JSON-строка с информацией о компании.
    """
    try:
        result = get_company_info(inn)

        if not result.get("ogrn") and not result.get("full_name"):
            return json.dumps(
                {"message": f"Компания с ИНН {inn} не найдена в СБАР"},
                ensure_ascii=False,
            )

        return json.dumps(result, ensure_ascii=False, indent=2)

    except Exception as e:
        return json.dumps(
            {"error": f"Ошибка СБАР: {str(e)[:300]}"},
            ensure_ascii=False,
        )