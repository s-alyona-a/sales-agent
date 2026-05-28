import json
from datetime import datetime, timedelta

from langchain_core.tools import tool
from ddgs import DDGS

from utils.web_reader import fetch_page_content, fetch_multiple_pages

import config


def _ddgs_search(query: str, max_results: int = 8, region: str = "ru-ru") -> list[dict]:
    """Внутренняя функция поиска через DuckDuckGo.

    Args:
        query: Поисковый запрос.
        max_results: Максимальное количество результатов.
        region: Регион поиска.

    Returns:
        Список словарей с результатами поиска.
    """
    kwargs = {
        "max_results": max_results,
        "region": region,
    }

    # Прокси (если задан)
    if config.DDGS_PROXY:
        kwargs["proxy"] = config.DDGS_PROXY
    print(query)
    with DDGS() as ddgs:
        results = list(ddgs.text(query, **kwargs))

    return results


def _ddgs_news(query: str, max_results: int = 8) -> list[dict]:
    """Поиск новостей через DuckDuckGo.

    Args:
        query: Поисковый запрос.
        max_results: Максимальное количество результатов.

    Returns:
        Список словарей с новостями.
    """
    kwargs = {
        "max_results": max_results,
        "region": "ru-ru",
    }

    if config.DDGS_PROXY:
        kwargs["proxy"] = config.DDGS_PROXY

    with DDGS() as ddgs:
        results = list(ddgs.news(query, **kwargs))

    return results


@tool
def web_search(query: str) -> str:
    """Поиск в интернете через DuckDuckGo.

    Используй для поиска информации о компании: сайт, руководство,
    ИНН, новости, отзывы и т.д. Возвращает заголовки, краткие
    описания и ссылки на найденные страницы.

    Для получения полного текста страниц используй read_web_page
    с URL из результатов поиска.

    Args:
        query: Поисковый запрос (лучше на русском языке).

    Returns:
        JSON-строка с результатами поиска.
    """
    try:
        results = _ddgs_search(query, max_results=8)

        if not results:
            return json.dumps(
                {"message": f"По запросу '{query}' ничего не найдено"},
                ensure_ascii=False,
            )

        formatted = []
        for r in results:
            formatted.append({
                "title": r.get("title", ""),
                "body": r.get("body", ""),
                "href": r.get("href", ""),
            })

        return json.dumps(formatted, ensure_ascii=False, indent=2)

    except Exception as e:
        return json.dumps(
            {"error": f"Ошибка поиска: {str(e)[:300]}"},
            ensure_ascii=False,
        )


@tool
def web_search_news(query: str) -> str:
    """Поиск новостей через DuckDuckGo.

    Специализированный поиск по новостным источникам. Возвращает
    более свежие результаты с датами публикаций. Используй для
    поиска актуальных новостей о компании (за последние 2 недели).

    Args:
        query: Поисковый запрос (название компании + "новости").

    Returns:
        JSON-строка с новостными результатами (с датами).
    """
    try:
        results = _ddgs_news(query, max_results=8)

        if not results:
            return json.dumps(
                {"message": f"Новости по запросу '{query}' не найдены"},
                ensure_ascii=False,
            )

        formatted = []
        for r in results:
            formatted.append({
                "title": r.get("title", ""),
                "body": r.get("body", ""),
                "href": r.get("href", ""),
                "source": r.get("source", ""),
                "date": r.get("date", ""),
            })

        return json.dumps(formatted, ensure_ascii=False, indent=2)

    except Exception as e:
        return json.dumps(
            {"error": f"Ошибка поиска новостей: {str(e)[:300]}"},
            ensure_ascii=False,
        )


@tool
def read_web_page(url: str) -> str:
    """Прочитать содержимое веб-страницы по URL.

    Загружает страницу и извлекает основной текстовый контент.
    Используй после web_search для детального изучения найденных
    страниц (новости, страница компании, вакансии и т.д.).

    Args:
        url: URL страницы для чтения.

    Returns:
        JSON-строка с заголовком, текстом и мета-описанием страницы.
    """
    result = fetch_page_content(url)
    return json.dumps(result, ensure_ascii=False, indent=2)


@tool
def search_company_vacancies(company_name: str) -> str:
    """Поиск открытых вакансий компании в интернете.

    Ищет вакансии на hh.ru, Работа.ру и других сайтах.
    Важно для анализа: массовый найм говорит о росте компании,
    а специфические вакансии — о направлении развития.

    Args:
        company_name: Название компании для поиска вакансий.

    Returns:
        JSON-строка с результатами поиска вакансий.
    """
    try:
        # Поиск на разных площадках
        queries = [
            f"{company_name} вакансии site:hh.ru",
            f"{company_name} вакансии работа",
        ]

        all_results = []
        seen_hrefs = set()

        for query in queries:
            results = _ddgs_search(query, max_results=5)
            for r in results:
                href = r.get("href", "")
                if href not in seen_hrefs:
                    seen_hrefs.add(href)
                    all_results.append({
                        "title": r.get("title", ""),
                        "body": r.get("body", ""),
                        "href": href,
                    })

        if not all_results:
            return json.dumps(
                {"message": f"Вакансии для '{company_name}' не найдены"},
                ensure_ascii=False,
            )

        return json.dumps(all_results, ensure_ascii=False, indent=2)

    except Exception as e:
        return json.dumps(
            {"error": f"Ошибка поиска вакансий: {str(e)[:300]}"},
            ensure_ascii=False,
        )


@tool
def search_company_leaders(company_name: str) -> str:
    """Поиск информации о руководстве компании в интернете.

    Ищет данные о ЛПР (лицах, принимающих решения): генеральный
    директор, замы, руководители направлений. Важно для подготовки
    к встрече — узнать, с кем предстоит общаться.

    Args:
        company_name: Название компании.

    Returns:
        JSON-строка с результатами поиска.
    """
    try:
        queries = [
            f"{company_name} генеральный директор руководство",
            f"{company_name} CEO руководитель",
        ]

        all_results = []
        seen_hrefs = set()

        for query in queries:
            results = _ddgs_search(query, max_results=5)
            for r in results:
                href = r.get("href", "")
                if href not in seen_hrefs:
                    seen_hrefs.add(href)
                    all_results.append({
                        "title": r.get("title", ""),
                        "body": r.get("body", ""),
                        "href": href,
                    })

        if not all_results:
            return json.dumps(
                {"message": f"Информация о руководстве '{company_name}' не найдена"},
                ensure_ascii=False,
            )

        # Читаем содержимое первых 2-3 страниц для детальной информации
        urls_to_read = [r["href"] for r in all_results[:2] if r["href"]]
        if urls_to_read:
            pages = fetch_multiple_pages(urls_to_read)
            for i, page in enumerate(pages):
                if page["success"] and page["text"]:
                    all_results[i]["page_content"] = page["text"][:2000]

        return json.dumps(all_results, ensure_ascii=False, indent=2)

    except Exception as e:
        return json.dumps(
            {"error": f"Ошибка поиска руководства: {str(e)[:300]}"},
            ensure_ascii=False,
        )


@tool
def search_company_inn(company_name: str) -> str:
    """Поиск ИНН и юридической информации о компании.

    Ищет ИНН, ОГРН, юридический адрес, дату регистрации
    и другие юридические данные компании.

    Args:
        company_name: Название компании.

    Returns:
        JSON-строка с результатами поиска.
    """
    try:
        queries = [
            f"{company_name} ИНН ОГРН",
            f"{company_name} сайт компании",
        ]

        all_results = []
        seen_hrefs = set()

        for query in queries:
            results = _ddgs_search(query, max_results=5)
            for r in results:
                href = r.get("href", "")
                if href not in seen_hrefs:
                    seen_hrefs.add(href)
                    all_results.append({
                        "title": r.get("title", ""),
                        "body": r.get("body", ""),
                        "href": href,
                    })

        if not all_results:
            return json.dumps(
                {"message": f"Юридическая информация о '{company_name}' не найдена"},
                ensure_ascii=False,
            )

        return json.dumps(all_results, ensure_ascii=False, indent=2)

    except Exception as e:
        return json.dumps(
            {"error": f"Ошибка поиска ИНН: {str(e)[:300]}"},
            ensure_ascii=False,
        )
