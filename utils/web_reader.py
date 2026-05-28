"""Утилита для чтения содержимого веб-страниц.

Использует httpx для загрузки и trafilatura для извлечения
основного текстового содержимого (без навигации, рекламы и т.д.).
"""

import httpx
import trafilatura
from bs4 import BeautifulSoup

import config


def fetch_page_content(url: str, timeout: int | None = None) -> dict:
    """Загрузка и извлечение текстового содержимого веб-страницы.

    Args:
        url: URL страницы.
        timeout: Таймаут в секундах (по умолчанию из конфига).

    Returns:
        Словарь с полями:
        - url: исходный URL
        - title: заголовок страницы
        - text: основной текст страницы
        - description: мета-описание
        - success: флаг успешной загрузки
        - error: сообщение об ошибке (если есть)
    """
    if timeout is None:
        timeout = config.WEB_READ_TIMEOUT

    result = {
        "url": url,
        "title": "",
        "text": "",
        "description": "",
        "success": False,
        "error": "",
    }

    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        }

        with httpx.Client(follow_redirects=True, timeout=timeout, verify=False) as client:
            response = client.get(url, headers=headers)
            response.raise_for_status()

        html = response.text

        # Извлечение заголовка и мета-описания через BeautifulSoup
        soup = BeautifulSoup(html, "lxml")
        title_tag = soup.find("title")
        if title_tag:
            result["title"] = title_tag.get_text(strip=True)

        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc and meta_desc.get("content"):
            result["description"] = meta_desc["content"].strip()

        # Извлечение основного текста через trafilatura
        extracted = trafilatura.extract(
            html,
            include_comments=False,
            include_tables=True,
            favor_precision=True,
        )

        if extracted:
            # Ограничиваем длину текста
            max_length = 5000
            if len(extracted) > max_length:
                extracted = extracted[:max_length] + "... [текст обрезан]"
            result["text"] = extracted
        else:
            # Fallback: извлекаем текст через BeautifulSoup
            for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
                tag.decompose()
            text = soup.get_text(separator="\n", strip=True)
            if len(text) > max_length:
                text = text[:max_length] + "... [текст обрезан]"
            result["text"] = text

        result["success"] = True

    except httpx.TimeoutException:
        result["error"] = f"Таймаут при загрузке страницы ({timeout}с)"
    except httpx.HTTPStatusError as e:
        result["error"] = f"HTTP ошибка: {e.response.status_code}"
    except Exception as e:
        result["error"] = f"Ошибка загрузки: {str(e)[:200]}"

    return result


def fetch_multiple_pages(urls: list[str], timeout: int | None = None) -> list[dict]:
    """Загрузка нескольких страниц последовательно.

    Args:
        urls: Список URL для загрузки.
        timeout: Таймаут для каждой страницы.

    Returns:
        Список результатов (словарей) для каждого URL.
    """
    results = []
    for url in urls[:config.MAX_PAGES_TO_READ]:
        page_result = fetch_page_content(url, timeout)
        results.append(page_result)
    return results