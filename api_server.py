"""FastAPI сервер для Sales Agent — интеграция с Electron+Svelte фронтендом.

Работает БЕЗ Docker — OpenSearch и CRM используют JSON-файлы.

Запуск:
    cd sales-agent
    pip install fastapi "uvicorn[standard]"
    python api_server.py                  # обычный режим
    python api_server.py --debug          # подробные логи + замеры времени
    python api_server.py --check          # проверить импорты без запуска сервера

Сервер: http://localhost:8900

Эндпоинты:
    GET  /health                    — проверка здоровья
    GET  /api/meetings/today        — встречи на сегодня (mock)
    POST /api/agent/collect-card    — сбор карточки (CRM + OpenSearch + WebSearch + LLM)
    POST /api/agent/collect-direct  — быстрый сбор без LLM
"""

import argparse
import json
import os
import platform
import re
import sys
import time
import traceback
from contextlib import asynccontextmanager
from typing import Any

# Убедимся, что sales-agent корень в sys.path
API_DIR = os.path.dirname(os.path.abspath(__file__))
if API_DIR not in sys.path:
    sys.path.insert(0, API_DIR)

import config


# ─── CLI-аргументы ──────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(description="Sales Agent API Server")
    parser.add_argument("--debug", action="store_true", help="Подробные логи и замеры времени")
    parser.add_argument("--check", action="store_true", help="Проверить импорты без запуска сервера")
    parser.add_argument("--no-reload", action="store_true", help="Отключить auto-reload (рекомендуется на Windows)")
    parser.add_argument("--port", type=int, default=8900, help="Порт сервера (по умолчанию 8900)")
    return parser.parse_args()


cli_args = parse_args()
DEBUG = cli_args.debug


def debug_log(msg: str):
    if DEBUG:
        print(f"  [DEBUG] {msg}")


# ─── Диагностика импортов ───────────────────────────────────────

def check_imports():
    """Проверка доступности всех модулей. Возвращает True, если всё ОК."""
    modules = [
        ("crm.mock_crm", "MockCRM"),
        ("opensearch.client", "OpenSearchClient"),
        ("agent.prompts", "ANALYSIS_SYSTEM_PROMPT"),
    ]

    # Опциональные — могут отсутствовать
    optional = [
        ("agent.pipeline", "collect_data"),
        ("agent.agent", "create_llm"),
        ("ddgs", "DDGS"),
        ("langchain_gigachat", "GigaChat"),
    ]

    all_ok = True
    print("\n📋 Проверка импортов:")
    for module_path, attr in modules:
        try:
            mod = __import__(module_path, fromlist=[attr])
            getattr(mod, attr)
            print(f"  ✅ {module_path}.{attr}")
        except Exception as e:
            print(f"  ❌ {module_path}.{attr} — {e}")
            all_ok = False

    for module_path, attr in optional:
        try:
            mod = __import__(module_path, fromlist=[attr])
            getattr(mod, attr)
            print(f"  ✅ {module_path}.{attr} (опциональный)")
        except Exception as e:
            print(f"  ⚠️  {module_path}.{attr} — {e} (опциональный)")

    return all_ok


if cli_args.check:
    ok = check_imports()
    sys.exit(0 if ok else 1)


# ─── Моковые встречи ───────────────────────────────────────────

MEETINGS_DATA = [
    {
        "id": 1, "time": "09:30", "duration": "60 мин",
        "client": 'ООО "ТехноСфера"', "contact": "Петров Алексей, IT-директор",
        "inn": "7736207543", "topic": "Внедрение BI-аналитики",
        "status": "done", "prepStatus": "ready", "tags": ["IT", "BI", "аналитика"],
    },
    {
        "id": 2, "time": "11:00", "duration": "45 мин",
        "client": 'АО "СтройИнвест"', "contact": "Волкова Анна, Финансовый директор",
        "inn": "7839397230", "topic": "Облачная телефония для 5 офисов",
        "status": "upcoming", "prepStatus": "ready", "tags": ["строительство", "телефония"],
    },
    {
        "id": 3, "time": "13:30", "duration": "30 мин",
        "client": 'ООО "ЛогистикПро"', "contact": "Иванов Игорь, Генеральный директор",
        "inn": "7826156685", "topic": "Автоматизация управления автопарком",
        "status": "upcoming", "prepStatus": "pending", "tags": ["логистика", "ERP"],
    },
    {
        "id": 4, "time": "15:00", "duration": "60 мин",
        "client": 'ПАО "АльфаЭнерго"', "contact": "Смирнова Елена, Зам. гендиректора по ИТ",
        "inn": "7706284124", "topic": "Кибербезопасность АСУ ТП — следующий этап",
        "status": "upcoming", "prepStatus": "pending", "tags": ["энергетика", "ИБ", "АСУ ТП"],
    },
    {
        "id": 5, "time": "16:30", "duration": "45 мин",
        "client": 'АО "РитейлГрупп"', "contact": "Кузнецова Ольга, Директор по развитию",
        "inn": "7707083893", "topic": "Оптимизация цепочек поставок, WMS",
        "status": "upcoming", "prepStatus": "pending", "tags": ["ритейл", "WMS", "логистика"],
    },
    {
        "id": 6, "time": "17:30", "duration": "45 мин",
        "client": "ГУП «МосТрансАвто»", "contact": "Петров Игорь, Зам. директора",
        "inn": "7705002602", "topic": "Масштабирование IoT-мониторинга автопарка",
        "status": "upcoming", "prepStatus": "pending", "tags": ["транспорт", "IoT", "мониторинг"],
    },
]


# ─── Мок-новости для демо-компаний (ключ — ИНН) ─────────────────
# Реальных новостей по этим компаниям в DDG нет, а text-фолбэк отдаёт
# просто веб-поиск по названию (сайты с ИНН и т.п.), а не новости.
# Поэтому для демо отдаём курируемые правдоподобные новости по теме.
MOCK_NEWS: dict[str, list[dict[str, str]]] = {
    # ООО "ТехноСфера" — BI-аналитика
    "7736207543": [
        {"title": "«ТехноСфера» запустила платформу предиктивной аналитики для ритейла",
         "body": "Компания представила BI-решение с прогнозированием спроса на базе машинного обучения.",
         "source": "РБК", "date": "2026-05-26", "href": "https://www.rbc.ru/technology_and_media/"},
        {"title": "«ТехноСфера» отчиталась о росте выручки на 28% по итогам 2025 года",
         "body": "Основной вклад дал сегмент корпоративной аналитики данных.",
         "source": "Ведомости", "date": "2026-05-21", "href": "https://www.vedomosti.ru/technology"},
        {"title": "«ТехноСфера» открыла центр разработки в Казани",
         "body": "Планируется нанять более 200 инженеров по данным и ML в течение года.",
         "source": "Коммерсантъ", "date": "2026-05-18", "href": "https://www.kommersant.ru/doc"},
    ],
    # АО "СтройИнвест" — облачная телефония
    "7839397230": [
        {"title": "«СтройИнвест» инвестирует 2 млрд руб. в цифровизацию офисов",
         "body": "Программа охватывает унифицированные коммуникации и облачную телефонию.",
         "source": "РБК", "date": "2026-05-27", "href": "https://www.rbc.ru/business/"},
        {"title": "«СтройИнвест» переводит коммуникации пяти филиалов в облако",
         "body": "Цель — единая номерная ёмкость и снижение затрат на связь.",
         "source": "Ведомости", "date": "2026-05-22", "href": "https://www.vedomosti.ru/business"},
        {"title": "«СтройИнвест» выиграл крупный тендер на застройку в Санкт-Петербурге",
         "body": "Проект предполагает ввод более 120 тыс. кв. м недвижимости.",
         "source": "Интерфакс", "date": "2026-05-17", "href": "https://www.interfax.ru/business/"},
    ],
    # ООО "ЛогистикПро" — автоматизация автопарка
    "7826156685": [
        {"title": "«ЛогистикПро» расширяет автопарк на 150 единиц техники",
         "body": "Рост связан с увеличением объёмов перевозок в Северо-Западном регионе.",
         "source": "РБК", "date": "2026-05-25", "href": "https://www.rbc.ru/business/"},
        {"title": "«ЛогистикПро» внедряет систему управления автопарком",
         "body": "Решение обеспечит мониторинг маршрутов и контроль расхода топлива.",
         "source": "Ведомости", "date": "2026-05-20", "href": "https://www.vedomosti.ru/business"},
        {"title": "«ЛогистикПро» открыла распределительный центр под Санкт-Петербургом",
         "body": "Площадь нового хаба превышает 25 тыс. кв. м.",
         "source": "ТАСС", "date": "2026-05-16", "href": "https://tass.ru/ekonomika"},
    ],
    # ПАО "АльфаЭнерго" — кибербезопасность АСУ ТП
    "7706284124": [
        {"title": "«АльфаЭнерго» усиливает защиту АСУ ТП на фоне роста атак на отрасль",
         "body": "Компания развёртывает систему мониторинга промышленных сетей.",
         "source": "Коммерсантъ", "date": "2026-05-28", "href": "https://www.kommersant.ru/doc"},
        {"title": "«АльфаЭнерго» инвестирует в кибербезопасность промышленных объектов",
         "body": "Бюджет программы защиты критической инфраструктуры увеличен вдвое.",
         "source": "РБК", "date": "2026-05-23", "href": "https://www.rbc.ru/business/"},
        {"title": "«АльфаЭнерго» прошла аудит информационной безопасности по требованиям ФСТЭК",
         "body": "Подтверждено соответствие требованиям к значимым объектам КИИ.",
         "source": "Интерфакс", "date": "2026-05-19", "href": "https://www.interfax.ru/business/"},
    ],
    # АО "РитейлГрупп" — цепочки поставок, WMS
    "7707083893": [
        {"title": "«РитейлГрупп» оптимизирует цепочки поставок с помощью WMS",
         "body": "Внедрение системы управления складом сократило сроки обработки заказов.",
         "source": "Ведомости", "date": "2026-05-26", "href": "https://www.vedomosti.ru/business"},
        {"title": "«РитейлГрупп» открыла 40 новых магазинов в регионах",
         "body": "Сеть продолжает экспансию в городах с населением от 100 тыс. человек.",
         "source": "РБК", "date": "2026-05-22", "href": "https://www.rbc.ru/business/"},
        {"title": "«РитейлГрупп» сообщила о росте онлайн-продаж на 35%",
         "body": "Компания развивает омниканальную модель и собственную доставку.",
         "source": "Коммерсантъ", "date": "2026-05-18", "href": "https://www.kommersant.ru/doc"},
    ],
    # ГУП «МосТрансАвто» — IoT-мониторинг автопарка
    "7705002602": [
        {"title": "«МосТрансАвто» оснастит автопарк системой IoT-мониторинга",
         "body": "Датчики обеспечат контроль состояния техники и расхода топлива в реальном времени.",
         "source": "РБК", "date": "2026-05-27", "href": "https://www.rbc.ru/business/"},
        {"title": "«МосТрансАвто» обновит более 500 единиц подвижного состава",
         "body": "Программа обновления рассчитана на ближайшие два года.",
         "source": "ТАСС", "date": "2026-05-24", "href": "https://tass.ru/ekonomika"},
        {"title": "«МосТрансАвто» внедряет цифровую систему контроля топлива",
         "body": "Ожидается снижение издержек на горюче-смазочные материалы.",
         "source": "Ведомости", "date": "2026-05-19", "href": "https://www.vedomosti.ru/business"},
    ],
}


# ─── Pydantic модели ────────────────────────────────────────────

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field


class CollectCardRequest(BaseModel):
    company_name: str = Field(..., alias="companyName")
    meeting_topic: str = Field(default="", alias="meetingTopic")
    inn: str = Field(default="", alias="inn")

    class Config:
        populate_by_name = True

class MeetingPlanRequest(BaseModel):
    company_name: str = Field(..., alias="companyName")
    meeting_topic: str = Field(default="", alias="meetingTopic")
    contact: str = Field(default="", alias="contact")
    card_data: dict = Field(default_factory=dict, alias="cardData")

    class Config:
        populate_by_name = True


# ─── Вспомогательные функции ────────────────────────────────────

def normalize_name(name: str) -> str:
    """Очистка названия компании от кавычек."""
    return re.sub(r'["«»\']', "", name).strip()


def strip_legal_prefix(name: str) -> str:
    """Удаление ОПФ (ООО, АО и т.д.)."""
    return re.sub(
        r"^(ООО|АО|ПАО|ЗАО|ОАО|ГУП|ФГУП|МУП|НКО|ИП)\s*", "",
        normalize_name(name),
    ).strip()


def to_camel_case(key: str) -> str:
    """Конвертация snake_case → camelCase."""
    components = key.split("_")
    return components[0] + "".join(x.title() for x in components[1:])


def normalize_response(data: Any) -> Any:
    """Рекурсивная конвертация всех ключей dict из snake_case в camelCase.

    Это нужно, потому что фронтенд (Svelte) ожидает camelCase,
    а Python-бэкенд отдаёт snake_case.
    """
    if isinstance(data, dict):
        return {to_camel_case(k): normalize_response(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [normalize_response(item) for item in data]
    return data


# ─── Сбор карточки (прямой, без LLM) ──────────────────────────

def collect_card_direct(company_name: str, meeting_topic: str, inn: str = "", on_step=None) -> dict[str, Any]:
    """Прямой сбор карточки: CRM (JSON) + OpenSearch (JSON) + WebSearch (DuckDuckGo).

    НЕ требует Docker. НЕ требует GigaChat.
    OpenSearch автоматически переключится на JSON-файл.
    INN-priority: если передан ИНН, сначала ищем по точному ИНН.
    """
    t_start = time.time()
    result: dict[str, Any] = {
        "company_name": company_name,
        "meeting_topic": meeting_topic,
        "inn": inn,
        "crm": {"client_info": None, "deals": [], "contacts": [], "interactions": []},
        "opensearch": [],
        "web_search": [],
        "web_news": [],
        "vacancies": [],
        "products": [],
        "sbar": {}
    }

    def step(name, status="running", detail=""):
        if on_step:
            on_step(name, status, detail)

    # ─── 1. CRM (INN-priority) ───
    step("crm", "running", "Поиск клиента в CRM")
    t1 = time.time()
    try:
        from crm.mock_crm import MockCRM
        crm = MockCRM()

        client_info = None

        # INN-priority: сначала точный поиск по ИНН
        if inn:
            client_info = crm.get_client_by_inn(inn)
            if client_info:
                debug_log(f"CRM: найдено по ИНН {inn}")

        # Fallback: поиск по названию
        if not client_info:
            client_info = crm.get_client_info(company_name)

        if client_info is None:
            search_results = crm.search_clients(normalize_name(company_name))
            if search_results:
                client_info = crm.get_client_info(search_results[0]["name"])

        if client_info is None:
            core_name = strip_legal_prefix(company_name)
            if core_name:
                search_results = crm.search_clients(core_name)
                if search_results:
                    client_info = crm.get_client_info(search_results[0]["name"])

        result["crm"]["client_info"] = client_info
        if client_info:
            client_id = client_info.get("id", "")
            result["crm"]["deals"] = crm.get_deals(client_id)
            result["crm"]["contacts"] = crm.get_contacts(client_id)
            result["crm"]["interactions"] = crm.get_interaction_history(client_id)
        result["products"] = crm.get_our_products()
    except Exception as e:
        result["crm_error"] = str(e)
        if DEBUG:
            traceback.print_exc()
    step("crm", "done", f"CRM: {'найден' if result['crm']['client_info'] else 'не найден'}")
    debug_log(f"CRM: {time.time() - t1:.2f}s")

    # ─── 2. OpenSearch (INN-priority) ───
    step("opensearch", "running", "Поиск во внутренней базе")
    t2 = time.time()
    try:
        from opensearch.client import OpenSearchClient
        os_client = OpenSearchClient()
        os_client.connect(force_mock=True)  # без Docker — сразу JSON

        os_results = []

        # INN-priority: сначала точный поиск по ИНН
        if inn:
            inn_result = os_client.search_by_inn(inn)
            if inn_result:
                os_results = [inn_result]
                debug_log(f"OpenSearch: найдено по ИНН {inn}")

        # Fallback: поиск по названию
        if not os_results:
            os_results = os_client.search(company_name, size=5)

        if not os_results:
            core_name = strip_legal_prefix(company_name)
            if core_name:
                os_results = os_client.search(core_name, size=5)

        result["opensearch"] = os_results
        os_client.close()
    except Exception as e:
        result["opensearch_error"] = str(e)
        if DEBUG:
            traceback.print_exc()
    step("opensearch", "done", f"OpenSearch: {len(result['opensearch'])} записей")
    debug_log(f"OpenSearch: {time.time() - t2:.2f}s")

    # ─── 3. Web Search (DuckDuckGo) ───
    step("web", "running", "Поиск в интернете")
    t3 = time.time()
    try:
        from ddgs import DDGS
        with DDGS() as ddgs:
            web_results = list(
                ddgs.text(f"{company_name} компания сайт", max_results=5, region="ru-ru")
            )
            result["web_search"] = [
                {"title": r.get("title", ""), "body": r.get("body", ""), "href": r.get("href", "")}
                for r in web_results
            ]
    except Exception as e:
        result["web_search_error"] = str(e)
        if DEBUG:
            traceback.print_exc()
    step("web", "done", f"Веб: {len(result.get('web_search', []))} результатов")
    debug_log(f"WebSearch: {time.time() - t3:.2f}s")

    # ─── 4. News ───
    step("news", "running", "Поиск новостей")
    t4 = time.time()
    try:
        from ddgs import DDGS
        from urllib.parse import urlparse

        core_name = strip_legal_prefix(company_name)
        query_name = core_name or company_name

        # Демо-компании с известным ИНН: отдаём курируемые новости.
        # По ним нет реальной выдачи в DDG, а text-фолбэк возвращает не новости,
        # а просто веб-поиск по названию (сайты с ИНН и т.п.).
        mock_news = MOCK_NEWS.get(inn) if inn else None

        def _news_relevant(item: dict) -> bool:
            """Отсев нерелевантной выдачи.

            ddgs.news() при отсутствии новостей по компании отдаёт мировую
            трендовую ленту (SpaceX, спорт и т.п.). Считаем новость релевантной,
            только если название компании реально встречается в заголовке/теле.
            """
            haystack = f"{item.get('title', '')} {item.get('body', '')}".lower()
            name = query_name.lower().strip()
            if not name:
                return True
            if name in haystack:
                return True
            # многословное название: релевантно, если найдены все значимые слова
            words = [w for w in name.split() if len(w) >= 4]
            return bool(words) and all(w in haystack for w in words)

        if mock_news:
            news_items = [dict(n) for n in mock_news]
        else:
            news_items = []

            # Сначала пробуем ddgs.news() (настоящие новости с датой и источником)
            try:
                with DDGS() as ddgs:
                    news_results = list(
                        ddgs.news(query_name, max_results=10, region="ru-ru")
                    )
                    for r in news_results:
                        item = {
                            "title": r.get("title", ""),
                            "body": r.get("body", ""),
                            "href": r.get("url", r.get("href", "")),
                            "date": r.get("date", ""),
                            "source": r.get("source", ""),
                        }
                        if _news_relevant(item):
                            news_items.append(item)
            except Exception:
                debug_log("ddgs.news() failed, fallback to text search")

            # Если news() не дал релевантных результатов — ищем по новостным сайтам через text()
            if not news_items:
                news_sites = "site:rbc.ru OR site:kommersant.ru OR site:vedomosti.ru OR site:tass.ru OR site:ria.ru OR site:interfax.ru"
                with DDGS() as ddgs:
                    text_results = list(
                        ddgs.text(
                            f"{query_name} {news_sites}",
                            max_results=10,
                            region="ru-ru",
                        )
                    )
                    for r in text_results:
                        href = r.get("href", "")
                        source = urlparse(href).netloc.replace("www.", "") if href else ""
                        item = {
                            "title": r.get("title", ""),
                            "body": r.get("body", ""),
                            "href": href,
                            "date": "",
                            "source": source,
                        }
                        if _news_relevant(item):
                            news_items.append(item)

        result["web_news"] = news_items[:5]
    except Exception as e:
        result["web_news_error"] = str(e)
        if DEBUG:
            traceback.print_exc()
    step("news", "done", f"Новости: {len(result.get('web_news', []))} шт.")
    debug_log(f"News: {time.time() - t4:.2f}s")

    # ─── 5. Vacancies ───
    step("vacancies", "running", "Поиск вакансий")
    t5 = time.time()
    try:
        from ddgs import DDGS
        with DDGS() as ddgs:
            vac_results = list(
                ddgs.text(f"{company_name} вакансии site:hh.ru", max_results=5, region="ru-ru")
            )
            result["vacancies"] = [
                {"title": r.get("title", ""), "body": r.get("body", ""), "href": r.get("href", "")}
                for r in vac_results
            ]
    except Exception as e:
        result["vacancies_error"] = str(e)
        if DEBUG:
            traceback.print_exc()
    step("vacancies", "done", f"Вакансии: {len(result.get('vacancies', []))} шт.")
    debug_log(f"Vacancies: {time.time() - t5:.2f}s")

    # ─── 6. СБАР (Sber Analytics) — по ИНН ───
    step("sbar", "running", "Запрос в СБАР по ИНН")
    t6 = time.time()
    try:
        if inn:
            from agent.tools.sbar_tool import get_company_info as sbar_get_company_info
            sbar_result = sbar_get_company_info(inn)
            result["sbar"] = sbar_result
            if sbar_result.get("ogrn"):
                debug_log(f"СБАР: найдена компания ОГРН={sbar_result['ogrn']}")
            else:
                debug_log(f"СБАР: компания с ИНН {inn} не найдена")
        else:
            debug_log("СБАР: пропущен (ИНН не указан)")
    except Exception as e:
        result["sbar_error"] = str(e)
        if DEBUG:
            traceback.print_exc()
    sbar_found = bool(result.get("sbar", {}).get("ogrn"))
    step("sbar", "done", f"СБАР: {'найдена' if sbar_found else 'не найдена'}")
    debug_log(f"СБАР: {time.time() - t6:.2f}s")

    debug_log(f"Итого: {time.time() - t_start:.2f}s")
    return result


# ─── Сбор карточки через pipeline + LLM ────────────────────────

def collect_card_with_pipeline(company_name: str, meeting_topic: str, inn: str = "") -> dict[str, Any]:
    """Сбор карточки через программный пайплайн + GigaChat-анализ.

    Использует agent.pipeline для сбора данных + agent.agent.run_pipeline для LLM.
    """
    from agent.agent import run_pipeline

    pipeline_result = run_pipeline(company_name, meeting_topic, inn)

    # Структурированные данные для UI (без LLM)
    structured = collect_card_direct(company_name, meeting_topic, inn)

    # Добавляем LLM-анализ
    structured["agent_analysis"] = pipeline_result.get("analysis", "")

    return structured


# ─── FastAPI приложение ─────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 Sales Agent API Server запускается...")
    print(f"   GigaChat: {'✓ настроен' if config.GIGACHAT_API_KEY else '✗ не настроен (прямой сбор)'}")
    print(f"   OpenSearch: JSON-файл (без Docker)")
    print(f"   Debug: {'ВКЛ' if DEBUG else 'выкл'}")

    # Проверяем импорты
    check_imports()

    yield
    print("👋 Sales Agent API Server останавливается...")


app = FastAPI(
    title="Sales Agent API",
    description="API для сбора карточек клиентов. Работает без Docker.",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "sales-agent-api",
        "opensearch_mode": "json-fallback",
        "debug": DEBUG,
    }


@app.get("/api/meetings/today")
async def get_meetings_today():
    return {"meetings": MEETINGS_DATA}


@app.post("/api/agent/collect-direct")
async def api_collect_direct(req: CollectCardRequest):
    """Быстрый сбор без LLM (5-15 сек). CRM + OpenSearch + WebSearch."""
    if not req.company_name:
        raise HTTPException(status_code=400, detail="companyName is required")

    t = time.time()
    try:
        data = collect_card_direct(req.company_name, req.meeting_topic, req.inn)
        camel_data = normalize_response(data)
        elapsed = time.time() - t
        return {"success": True, "data": camel_data, "elapsed_seconds": round(elapsed, 2)}
    except Exception as e:
        if DEBUG:
            traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/agent/collect-stream")
async def api_collect_stream(req: CollectCardRequest):
    """SSE-стрим сбора карточки с прогрессом шагов."""
    from starlette.responses import StreamingResponse
    import queue, threading

    if not req.company_name:
        raise HTTPException(status_code=400, detail="companyName is required")

    q: queue.Queue = queue.Queue()

    def on_step(name, status, detail):
        q.put(json.dumps({"type": "step", "step": name, "status": status, "detail": detail}))

    def run_collect():
        try:
            data = collect_card_direct(req.company_name, req.meeting_topic, req.inn, on_step=on_step)
            camel_data = normalize_response(data)
            q.put(json.dumps({"type": "result", "success": True, "data": camel_data}))
        except Exception as e:
            q.put(json.dumps({"type": "error", "error": str(e)}))
        finally:
            q.put(None)

    threading.Thread(target=run_collect, daemon=True).start()

    def event_stream():
        while True:
            msg = q.get()
            if msg is None:
                break
            yield f"data: {msg}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/agent/collect-card")
async def api_collect_card(req: CollectCardRequest):
    """Полный сбор с LLM-агентом (30-120 сек). Авто-fallback на прямой."""
    if not req.company_name:
        raise HTTPException(status_code=400, detail="companyName is required")

    if not config.GIGACHAT_API_KEY:
        try:
            data = collect_card_direct(req.company_name, req.meeting_topic, req.inn)
            camel_data = normalize_response(data)
            return {
                "success": True, "data": camel_data,
                "warning": "GigaChat не настроен — используется прямой сбор без LLM",
            }
        except Exception as e:
            if DEBUG:
                traceback.print_exc()
            raise HTTPException(status_code=500, detail=str(e))

    try:
        data = collect_card_with_pipeline(req.company_name, req.meeting_topic, req.inn)
        camel_data = normalize_response(data)
        return {"success": True, "data": camel_data}
    except Exception as e:
        if DEBUG:
            traceback.print_exc()
        try:
            data = collect_card_direct(req.company_name, req.meeting_topic, req.inn)
            camel_data = normalize_response(data)
            return {
                "success": True, "data": camel_data,
                "warning": f"Ошибка агента: {str(e)}. Использован прямой сбор.",
            }
        except Exception as e2:
            if DEBUG:
                traceback.print_exc()
            raise HTTPException(status_code=500, detail=str(e2))

# ─── Meeting Plan ──────────────────────────────────────────────────

def _summarize_card_for_plan(card_data: dict) -> str:
    """Формирует краткую сводку из card_data для промпта плана встречи."""
    lines = []

    ci = card_data.get("crm", {}).get("clientInfo") or card_data.get("crm", {}).get("client_info")
    if ci:
        if ci.get("industry"):
            lines.append(f"Отрасль: {ci['industry']}")
        if ci.get("description"):
            lines.append(f"Описание: {ci['description']}")
        if ci.get("status"):
            lines.append(f"Статус клиента: {ci['status']}")

    os_list = card_data.get("opensearch", [])
    if os_list:
        os = os_list[0]
        rev = os.get("revenue") or os.get("employeeCount")
        if os.get("revenue"):
            lines.append(f"Выручка: {os['revenue']:,.0f} руб.")
        if os.get("employee_count") or os.get("employeeCount"):
            lines.append(f"Сотрудников: {os.get('employee_count') or os.get('employeeCount')}")
        if os.get("region"):
            lines.append(f"Регион: {os['region']}")
        if os.get("notes"):
            lines.append(f"Заметки: {os['notes']}")
        if os.get("internal_rating") or os.get("internalRating"):
            lines.append(f"Внутренний рейтинг: {os.get('internal_rating') or os.get('internalRating')}/10")

    deals = card_data.get("crm", {}).get("deals", [])
    if deals:
        lines.append(f"\nСделки ({len(deals)}):")
        for d in deals:
            status = d.get("status", "?")
            title = d.get("title", "?")
            amount = d.get("amount", 0)
            products = ", ".join(d.get("products", []))
            lines.append(f"  [{status}] {title} — {amount:,.0f}₽ ({products})")

    contacts = card_data.get("crm", {}).get("contacts", [])
    if contacts:
        lines.append(f"\nКонтакты ({len(contacts)}):")
        for c in contacts:
            lpr = " ⭐ЛПР" if c.get("is_lpr") or c.get("isLpr") else ""
            lines.append(f"  {c.get('name', '?')} — {c.get('position', '?')}{lpr}")
            if c.get("notes"):
                lines.append(f"    Заметки: {c['notes']}")

    interactions = card_data.get("crm", {}).get("interactions", [])
    if interactions:
        lines.append(f"\nПоследние взаимодействия ({len(interactions)}):")
        for h in interactions[-5:]:
            lines.append(f"  [{h.get('date', '?')}] {h.get('type', '?')}: {h.get('description', '')} → {h.get('outcome', '')}")

    news = card_data.get("webNews") or card_data.get("web_news", [])
    if news:
        lines.append(f"\nНовости ({len(news)}):")
        for n in news[:3]:
            lines.append(f"  {n.get('title', '')}")

    products = card_data.get("products", [])
    if products:
        lines.append(f"\nНаш каталог ({len(products)} продуктов):")
        for p in products:
            target = ", ".join(p.get("target_industries") or p.get("targetIndustries") or [])
            lines.append(f"  {p.get('name', '')} ({p.get('category', '')}) — для: {target}")

    return "\n".join(lines) if lines else "Данные о клиенте не собраны."


def _generate_template_plan(company_name: str, meeting_topic: str, contact: str, card_data: dict) -> dict:
    """Генерирует шаблонный план встречи без LLM."""
    ci = card_data.get("crm", {}).get("clientInfo") or card_data.get("crm", {}).get("client_info") or {}
    deals = card_data.get("crm", {}).get("deals", [])
    contacts = card_data.get("crm", {}).get("contacts", [])
    os_list = card_data.get("opensearch", [])
    os = os_list[0] if os_list else {}

    open_deals = [d for d in deals if d.get("status") in ("in_progress", "negotiation")]
    won_deals = [d for d in deals if d.get("status") == "won"]
    industry = ci.get("industry", "")

    lpr_names = [c.get("name", "") for c in contacts if c.get("is_lpr") or c.get("isLpr")]

    goal = f"Обсудить {meeting_topic} с {company_name}"
    if open_deals:
        goal += f", продвинуть {len(open_deals)} открытых сделок"

    questions = [
        f"Какие приоритетные задачи стоят перед {company_name} в этом квартале?",
        f"Какие проблемы сейчас решаете в области {meeting_topic.lower()}?",
        "Какой бюджет и сроки закладываете на этот проект?",
        "Кто ещё участвует в принятии решения?",
    ]
    if os.get("notes"):
        questions.append(f"Актуально ли по-прежнему: {os['notes'][:80]}?")

    talking_points = []
    if won_deals:
        total_won = sum(d.get("amount", 0) for d in won_deals)
        talking_points.append(f"Успешная история сотрудничества: {len(won_deals)} завершённых проектов на {total_won:,.0f} ₽")
    if industry:
        talking_points.append(f"Экспертиза в отрасли «{industry}»")
    talking_points.append(f"Наше решение закрывает потребность по теме «{meeting_topic}»")

    objections = [
        {"objection": "Дорого", "response": "Рассчитать ROI на конкретных метриках клиента, показать окупаемость"},
        {"objection": "Уже есть решение", "response": "Уточнить что не устраивает в текущем, предложить пилот для сравнения"},
    ]
    if open_deals:
        objections.append({"objection": "Нужно время подумать", "response": "Предложить конкретный следующий шаг с дедлайном"})

    return {
        "goal": goal,
        "agenda": [
            {"time": "5 мин", "topic": "Приветствие", "notes": f"Small talk, упомянуть {contact or 'контакт'}"},
            {"time": "10 мин", "topic": "Текущая ситуация", "notes": f"Узнать актуальные задачи по теме «{meeting_topic}»"},
            {"time": "15 мин", "topic": "Презентация решения", "notes": f"Показать как наш продукт решает задачу"},
            {"time": "10 мин", "topic": "Обсуждение условий", "notes": "Бюджет, сроки, формат пилота"},
            {"time": "5 мин", "topic": "Следующие шаги", "notes": "Договориться о конкретном действии"},
        ],
        "keyQuestions": questions,
        "talkingPoints": talking_points,
        "objections": objections,
        "nextSteps": [
            "Назначить демо/пилот с техническими специалистами",
            "Подготовить КП с расчётом ROI",
            "Назначить дату следующей встречи",
        ],
    }


@app.post("/api/agent/meeting-plan")
async def api_meeting_plan(req: MeetingPlanRequest):
    """Генерация плана встречи на основе карточки клиента."""
    if not req.company_name:
        raise HTTPException(status_code=400, detail="companyName is required")

    t = time.time()
    card_summary = _summarize_card_for_plan(req.card_data)

    # Пробуем LLM
    if config.GIGACHAT_API_KEY:
        try:
            from agent.agent import create_llm
            from agent.prompts import MEETING_PLAN_SYSTEM_PROMPT, MEETING_PLAN_HUMAN_TEMPLATE
            from langchain_core.messages import SystemMessage, HumanMessage

            llm = create_llm()
            human = MEETING_PLAN_HUMAN_TEMPLATE.format(
                company_name=req.company_name,
                meeting_topic=req.meeting_topic,
                contact=req.contact,
                card_summary=card_summary,
            )
            response = llm.invoke([
                SystemMessage(content=MEETING_PLAN_SYSTEM_PROMPT),
                HumanMessage(content=human),
            ])

            raw = response.content.strip()
            # Извлекаем JSON из ответа
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0].strip()
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0].strip()

            plan = json.loads(raw)
            elapsed = time.time() - t
            return {"success": True, "plan": plan, "source": "llm", "elapsed_seconds": round(elapsed, 2)}
        except Exception as e:
            debug_log(f"LLM plan failed: {e}")
            if DEBUG:
                traceback.print_exc()

    # Fallback: шаблонный план
    plan = _generate_template_plan(req.company_name, req.meeting_topic, req.contact, req.card_data)
    elapsed = time.time() - t
    return {"success": True, "plan": plan, "source": "template", "elapsed_seconds": round(elapsed, 2)}


@app.get("/api/agent/info")
async def api_agent_info():
    """Активная LLM для анализа карточки и генерации плана встречи (для UI-индикатора)."""
    llm_enabled = bool(config.GIGACHAT_API_KEY)
    return {
        "llm": {
            "enabled": llm_enabled,
            "provider": "GigaChat" if llm_enabled else None,
            "model": config.GIGACHAT_MODEL if llm_enabled else None,
        }
    }


# ─── Card Persistence (CRUD) ─────────────────────────────────────

@app.get("/api/cards")
async def api_get_cards(company_name: str = Query(default="", alias="companyName")):
    """Получить карточку по companyName или список всех карточек.

    GET /api/cards?companyName=... — загрузить конкретную карточку
    GET /api/cards               — список всех сохранённых карточек
    """
    try:
        from db import get_card, list_cards
    except ImportError:
        raise HTTPException(status_code=500, detail="Модуль db не найден")

    if company_name:
        # Загрузить конкретную карточку
        row = get_card(company_name)
        if row is None:
            return {"found": False, "data": None}

        card_data = json.loads(row.get("card_data", "{}"))
        return {
            "found": True,
            "data": card_data,
            "hasLLMAnalysis": bool(row.get("has_llm_analysis")),
            "updatedAt": row.get("updated_at", ""),
        }
    else:
        # Список всех карточек
        cards = list_cards()
        return {
            "cards": [
                {
                    "companyName": c["company_name"],
                    "meetingTopic": c.get("meeting_topic", ""),
                    "hasLLMAnalysis": bool(c.get("has_llm_analysis")),
                    "updatedAt": c.get("updated_at", ""),
                }
                for c in cards
            ]
        }


@app.delete("/api/cards")
async def api_delete_card(company_name: str = Query(..., alias="companyName")):
    """Удалить карточку по companyName."""
    try:
        from db import delete_card as db_delete_card
    except ImportError:
        raise HTTPException(status_code=500, detail="Модуль db не найден")

    deleted = db_delete_card(company_name)
    if deleted:
        return {"success": True, "message": f"Карточка '{company_name}' удалена"}
    else:
        return {"success": False, "message": f"Карточка '{company_name}' не найдена"}

# ─── Точка входа ────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    port = cli_args.port or int(os.getenv("SALES_AGENT_PORT", "8900"))

    # На Windows reload=True вызывает зависание — отключаем по умолчанию
    is_windows = platform.system() == "Windows"
    use_reload = not (cli_args.no_reload or is_windows)

    print(f"Zapusk na portu {port}")
    print(f"   Platform: {platform.system()}")
    print(f"   Auto-reload: {'ON' if use_reload else 'OFF'}")
    print(f"   Debug: {'ON' if DEBUG else 'off'}")

    uvicorn.run(
        "api_server:app",
        host="127.0.0.1",
        port=port,
        reload=use_reload,
        reload_dirs=[API_DIR] if use_reload else None,
    )