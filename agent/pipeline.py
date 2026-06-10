"""Оркестратор сбора данных — программный пайплайн.

Вместо ReAct-агента, который зависит от способности модели
вызывать инструменты, используется детерминированный пайплайн:
1. Программно вызываем все источники данных по порядку
2. Собираем результаты в единую структуру
3. Передаём LLM для анализа и генерации карточки

Это гарантирует, что ВСЕ источники данных будут опрошены.
"""

import json
from dataclasses import dataclass, field
from typing import Any
from datetime import datetime

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from opensearch.client import OpenSearchClient
from crm.mock_crm import MockCRM
from utils.web_reader import fetch_page_content, fetch_multiple_pages

from ddgs import DDGS

import config

from pathlib import Path

console = Console()


@dataclass
class ClientData:
    """Собранные данные о клиенте из всех источников."""

    company_name: str = ""
    meeting_topic: str = ""
    inn: str = ""

    # OpenSearch
    os_results: list[dict] = field(default_factory=list)

    # CRM
    crm_client_info: dict | None = None
    crm_deals: list[dict] = field(default_factory=list)
    crm_contacts: list[dict] = field(default_factory=list)
    crm_interactions: list[dict] = field(default_factory=list)
    crm_products: list[dict] = field(default_factory=list)

    # Web: общая информация
    web_general: list[dict] = field(default_factory=list)
    web_inn: list[dict] = field(default_factory=list)

    # Web: новости
    web_news: list[dict] = field(default_factory=list)
    web_news_content: list[dict] = field(default_factory=list)

    # Web: руководство
    web_leaders: list[dict] = field(default_factory=list)
    web_leaders_content: list[dict] = field(default_factory=list)

    # Web: вакансии
    web_vacancies: list[dict] = field(default_factory=list)

    # СБАР (Sber Analytics)
    sbar_data: dict = field(default_factory=dict)

    # Ошибки
    errors: list[str] = field(default_factory=list)

    def to_context_string(self) -> str:
        """Сериализация собранных данных в строку для LLM-промпта."""
        sections = []

        # === Основная информация ===
        sections.append(f"## Компания: {self.company_name}")
        sections.append(f"## Тема встречи: {self.meeting_topic}")

        # === OpenSearch ===
        if self.os_results:
            sections.append("\n## Данные из внутренней базы (OpenSearch)")
            for r in self.os_results:
                sections.append(f"### {r.get('company_name', 'N/A')}")
                for key in ["inn", "industry", "okved", "okved_description", "description",
                             "website", "region", "employee_count", "tags", "notes",
                             "internal_rating", "last_meeting_date"]:
                    val = r.get(key)
                    if val:
                        if isinstance(val, list):
                            val = ", ".join(str(v) for v in val)
                        sections.append(f"- **{key}**: {val}")
        else:
            sections.append("\n## Данные из внутренней базы (OpenSearch)\nНе найдены.")

        # === CRM: карточка клиента ===
        if self.crm_client_info:
            sections.append("\n## Карточка клиента (CRM)")
            for key, val in self.crm_client_info.items():
                if val:
                    sections.append(f"- **{key}**: {val}")
        else:
            sections.append("\n## Карточка клиента (CRM)\nНе найдена.")

        # === CRM: сделки ===
        if self.crm_deals:
            sections.append("\n## Сделки (CRM)")
            for d in self.crm_deals:
                products = ", ".join(d.get("products", []))
                sections.append(
                    f"- [{d.get('status', '?')}] {d.get('title', '?')} | "
                    f"Сумма: {d.get('amount', 0):,.0f}₽ | "
                    f"Продукты: {products} | "
                    f"Создана: {d.get('created_at', '?')} | "
                    f"Закрыта: {d.get('closed_at', '—')} | "
                    f"Описание: {d.get('description', '')}"
                )
        else:
            sections.append("\n## Сделки (CRM)\nНет данных о сделках.")

        # === CRM: контакты ===
        if self.crm_contacts:
            sections.append("\n## Контактные лица (CRM)")
            for c in self.crm_contacts:
                lpr = "⭐ ЛПР" if c.get("is_lpr") else ""
                sections.append(
                    f"- {c.get('name', '?')} | {c.get('position', '?')} {lpr} | "
                    f"Email: {c.get('email', '—')} | Тел: {c.get('phone', '—')} | "
                    f"Последний контакт: {c.get('last_contact_date', '—')} | "
                    f"Заметки: {c.get('notes', '')}"
                )
        else:
            sections.append("\n## Контактные лица (CRM)\nНет данных о контактах.")

        # === CRM: взаимодействия ===
        if self.crm_interactions:
            sections.append("\n## История взаимодействий (CRM)")
            for h in self.crm_interactions:
                sections.append(
                    f"- [{h.get('date', '?')}] {h.get('type', '?')} | "
                    f"Менеджер: {h.get('manager', '?')} | "
                    f"{h.get('description', '')} → {h.get('outcome', '')}"
                )
        else:
            sections.append("\n## История взаимодействий (CRM)\nНет данных.")

        # === Web: общая информация ===
        if self.web_general:
            sections.append("\n## Поиск в интернете — общая информация")
            for r in self.web_general[:6]:
                sections.append(f"- **{r.get('title', '')}**: {r.get('body', '')} [🔗]({r.get('href', '')})")
        else:
            sections.append("\n## Поиск в интернете — общая информация\nНе найдено.")

        # === Web: ИНН ===
        if self.web_inn:
            sections.append("\n## ИНН и юридическая информация")
            for r in self.web_inn[:4]:
                sections.append(f"- **{r.get('title', '')}**: {r.get('body', '')} [🔗]({r.get('href', '')})")
        else:
            sections.append("\n## ИНН и юридическая информация\nНе найдено.")

        # === Web: новости ===
        if self.web_news:
            sections.append("\n## Новости")
            for r in self.web_news[:6]:
                date = r.get("date", "")
                source = r.get("source", "")
                sections.append(
                    f"- **{r.get('title', '')}** ({date}, {source}): "
                    f"{r.get('body', '')} [🔗]({r.get('href', '')})"
                )
        else:
            sections.append("\n## Новости\nНе найдено.")

        # === Web: содержимое новостей ===
        if self.web_news_content:
            sections.append("\n## Тексты новостных статей")
            for i, page in enumerate(self.web_news_content):
                if page.get("success") and page.get("text"):
                    sections.append(f"### Статья {i+1}: {page.get('title', 'Без заголовка')}")
                    sections.append(f"URL: {page.get('url', '')}")
                    sections.append(page["text"][:3000])
                    sections.append("")
        else:
            sections.append("\n## Тексты новостных статей\nНе удалось загрузить.")

        # === Web: руководство ===
        if self.web_leaders:
            sections.append("\n## Руководство компании (из интернета)")
            for r in self.web_leaders[:5]:
                sections.append(f"- **{r.get('title', '')}**: {r.get('body', '')} [🔗]({r.get('href', '')})")
        else:
            sections.append("\n## Руководство компании (из интернета)\nНе найдено.")

        # === Web: содержимое страниц о руководстве ===
        if self.web_leaders_content:
            sections.append("\n## Подробная информация о руководстве")
            for i, page in enumerate(self.web_leaders_content):
                if page.get("success") and page.get("text"):
                    sections.append(f"### Источник {i+1}: {page.get('title', 'Без заголовка')}")
                    sections.append(f"URL: {page.get('url', '')}")
                    sections.append(page["text"][:2000])
                    sections.append("")

        # === Web: вакансии ===
        if self.web_vacancies:
            sections.append("\n## Открытые вакансии")
            for r in self.web_vacancies[:8]:
                sections.append(f"- **{r.get('title', '')}**: {r.get('body', '')} [🔗]({r.get('href', '')})")
        else:
            sections.append("\n## Открытые вакансии\nНе найдено.")

        # === Каталог продуктов ===
        if self.crm_products:
            sections.append("\n## Наш каталог продуктов и услуг")
            for p in self.crm_products:
                target = ", ".join(p.get("target_industries", []))
                sections.append(
                    f"- **{p.get('name', '')}** ({p.get('category', '')}): "
                    f"{p.get('description', '')} | Целевые отрасли: {target}"
                )
        else:
            sections.append("\n## Наш каталог продуктов и услуг\nНе загружен.")

            # === СБАР (Sber Analytics) ===
            if self.sbar_data:
                sections.append("\n## Данные из СБАР (Sber Analytics)")

                if self.sbar_data.get("full_name"):
                    sections.append(f"- **Полное наименование**: {self.sbar_data['full_name']}")
                if self.sbar_data.get("ogrn"):
                    sections.append(f"- **ОГРН**: {self.sbar_data['ogrn']}")
                if self.sbar_data.get("main_activity"):
                    sections.append(f"- **Основной вид деятельности**: {self.sbar_data['main_activity']}")
                if self.sbar_data.get("main_activity_code"):
                    sections.append(f"- **Код основного ОКВЭД**: {self.sbar_data['main_activity_code']}")

                okveds = self.sbar_data.get("okved", [])
                if okveds:
                    sections.append("\n### ОКВЭД (все)")
                    for o in okveds:
                        sections.append(f"  - {o.get('code', '')}: {o.get('name', '')}")

                participants = self.sbar_data.get("participants", [])
                if participants:
                    sections.append("\n### Руководство и учредители (из СБАР)")
                    for p in participants:
                        sections.append(f"  - **{p.get('role', '')}**: {p.get('name', '')}")

                egrul = self.sbar_data.get("egrul", [])
                if egrul:
                    sections.append("\n### Записи ЕГРЮЛ")
                    for e in egrul[:10]:  # ограничиваем 10 записями
                        sections.append(f"  - [{e.get('register_date', '?')}] {e.get('name', '')}")
            else:
                sections.append(
                    "\n## Данные из СБАР (Sber Analytics)\nНе найдены (ИНН не указан или компания не найдена).")

        # === Ошибки ===
        if self.errors:
            sections.append("\n## ⚠️ Ошибки при сборе данных")
            for e in self.errors:
                sections.append(f"- {e}")

        return "\n".join(sections)

    def save_to_markdown(self, filename: str = None) -> str:
        """Сохраняет данные в Markdown файл."""
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"client_report_{self.company_name}_{timestamp}.md"

        # Используем существующий метод to_context_string
        content = self.to_context_string()

        # Добавляем заголовок и метаданные
        header = f"""# Отчет по компании: {self.company_name}
        **Дата формирования:** {datetime.now().strftime("%d.%m.%Y %H:%M:%S")}
        **Тема встречи:** {self.meeting_topic}

        ---
        """

        with open(filename, 'w', encoding='utf-8') as f:
            f.write(header + content)

        return filename


def _ddgs_search(query: str, max_results: int = 8) -> list[dict]:
    """Поиск через DuckDuckGo с обработкой ошибок."""
    kwargs = {
        "max_results": max_results,
        "region": "ru-ru",
    }
    if config.DDGS_PROXY:
        kwargs["proxy"] = config.DDGS_PROXY
    print(f'QUERY: {query}')
    print(f'KWARGS: {kwargs}')

    try:
        with DDGS() as ddgs:
            return list(ddgs.text(query, **kwargs))
    except Exception as e:
        print(f'SEARCH ERROR: {e}')


def _ddgs_news(query: str, max_results: int = 8) -> list[dict]:
    """Поиск новостей через DuckDuckGo."""
    kwargs = {
        "max_results": max_results,
        "region": "ru-ru",
    }
    if config.DDGS_PROXY:
        kwargs["proxy"] = config.DDGS_PROXY

    with DDGS() as ddgs:
        return list(ddgs.text(query, **kwargs))



def collect_data(company_name: str, meeting_topic: str, inn: str = "") -> ClientData:
    """Сбор данных о клиенте из всех источников.

    Args:
        company_name: Название компании.
        meeting_topic: Тема встречи.

    Returns:
        Объект ClientData со всеми собранными данными.
    """
    data = ClientData(
        company_name=company_name,
        meeting_topic=meeting_topic,
        inn=inn
    )

    # Инициализация клиентов
    os_client = OpenSearchClient()
    os_client.connect()
    crm = MockCRM()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:

        # === Шаг 1: OpenSearch ===
        task = progress.add_task("[cyan]1/7 Поиск во внутренней базе (OpenSearch)...", total=None)
        try:
            # Приоритет: сначала по ИНН (точное совпадение)
            if inn:
                results = os_client.search(inn, size=5)
            else:
                results = []

            # Фолбэк: по названию компании
            if not results:
                results = os_client.search(company_name, size=5)

            data.os_results = results
        except Exception as e:
            data.errors.append(f"OpenSearch: {e}")
        progress.remove_task(task)

        # === Шаг 2: CRM ===
        task = progress.add_task("[cyan]2/7 Поиск в CRM...", total=None)
        try:
            client_info = None

            # Приоритет 1: по ИНН (точное совпадение)
            if inn:
                client_info = crm.get_client_by_inn(inn)

            # Приоритет 2: по названию компании
            if client_info is None:
                client_info = crm.get_client_info(company_name)

            # Приоритет 3: поиск по подстроке
            if client_info is None:
                search_results = crm.search_clients(company_name)
                if search_results:
                    client_info = crm.get_client_info(search_results[0]["name"])

            if client_info:
                data.crm_client_info = client_info
                client_id = client_info.get("id", "")
                data.crm_deals = crm.get_deals(client_id)
                data.crm_contacts = crm.get_contacts(client_id)
                data.crm_interactions = crm.get_interaction_history(client_id)
        except Exception as e:
            data.errors.append(f"CRM: {e}")
        progress.remove_task(task)

        # === Шаг 3: Каталог продуктов ===
        task = progress.add_task("[cyan]3/7 Загрузка каталога продуктов...", total=None)
        try:
            data.crm_products = crm.get_our_products()
        except Exception as e:
            data.errors.append(f"Каталог продуктов: {e}")
        progress.remove_task(task)

        # === Шаг 4: Web — общая информация + ИНН ===
        task = progress.add_task("[cyan]4/7 Поиск в интернете — общая информация...", total=None)
        try:
            # Общий поиск
            data.web_general = _ddgs_search(f"{company_name} компания", max_results=6)
        except Exception as e:
            data.errors.append(f"Web-поиск (общий): {e}")

        try:
            # ИНН
            data.web_inn = _ddgs_search(f"{company_name} ИНН ОГРН", max_results=4)
        except Exception as e:
            data.errors.append(f"Web-поиск (ИНН): {e}")
        progress.remove_task(task)

        # === Шаг 5: Web — новости ===
        task = progress.add_task("[cyan]5/7 Поиск новостей о компании...", total=None)
        try:
            data.web_news = _ddgs_news(f"{company_name} новости", max_results=6)

            # Читаем содержимое новостных статей
            if data.web_news:
                news_urls = [r.get("href", "") for r in data.web_news[:3] if r.get("href")]
                if news_urls:
                    data.web_news_content = fetch_multiple_pages(news_urls)
        except Exception as e:
            data.errors.append(f"Web-поиск (новости): {e}")
        progress.remove_task(task)

        # === Шаг 6: Web — руководство ===
        task = progress.add_task("[cyan]6/7 Поиск информации о руководстве...", total=None)
        try:
            queries = [
                f"{company_name} генеральный директор руководство",
                f"{company_name} CEO",
            ]
            all_leaders = []
            seen = set()
            for q in queries:
                results = _ddgs_search(q, max_results=5)
                for r in results:
                    href = r.get("href", "")
                    if href not in seen:
                        seen.add(href)
                        all_leaders.append(r)

            data.web_leaders = all_leaders

            # Читаем страницы с информацией о руководстве
            if all_leaders:
                leader_urls = [r.get("href", "") for r in all_leaders[:2] if r.get("href")]
                if leader_urls:
                    data.web_leaders_content = fetch_multiple_pages(leader_urls)
        except Exception as e:
            data.errors.append(f"Web-поиск (руководство): {e}")
        progress.remove_task(task)

        # === Шаг 7: Web — вакансии ===
        task = progress.add_task("[cyan]7/7 Поиск вакансий компании...", total=None)
        try:
            queries = [
                f"{company_name} вакансии site:hh.ru",
                f"{company_name} вакансии работа",
            ]
            all_vacancies = []
            seen = set()
            for q in queries:
                results = _ddgs_search(q, max_results=5)
                for r in results:
                    href = r.get("href", "")
                    if href not in seen:
                        seen.add(href)
                        all_vacancies.append(r)

            data.web_vacancies = all_vacancies
        except Exception as e:
            data.errors.append(f"Web-поиск (вакансии): {e}")
        progress.remove_task(task)

        # === Шаг 8: СБАР (Sber Analytics) — по ИНН ===
        task = progress.add_task("[cyan]8/8 Поиск в СБАР по ИНН...", total=None)
        try:
            if inn:
                from agent.tools.sbar_tool import get_company_info as sbar_get_company_info
                sbar_result = sbar_get_company_info(inn)
                data.sbar_data = sbar_result
                if sbar_result.get("ogrn"):
                    print(f"   ✓ СБАР: найдена компания ОГРН={sbar_result['ogrn']}")
                else:
                    print(f"   ⚠ СБАР: компания с ИНН {inn} не найдена")
            else:
                print("   ⏭ СБАР: пропущен (ИНН не указан)")
        except Exception as e:
            data.errors.append(f"СБАР: {e}")
        progress.remove_task(task)

        # === Шаг 9: LLM-подбор релевантных продуктов ===
        task = progress.add_task("[cyan]9/9 Подбор релевантных продуктов (LLM)...", total=None)
        try:
            from agent.product_matcher import enrich_products_with_recommendations

            # Формируем card_data для product_matcher из уже собранных данных
            card_data_dict = {
                "company_name": data.company_name,
                "meeting_topic": data.meeting_topic,
                "inn": data.inn,
                "crm": {
                    "client_info": data.crm_client_info,
                    "deals": data.crm_deals,
                    "contacts": data.crm_contacts,
                    "interactions": data.crm_interactions,
                },
                "opensearch": data.os_results,
                "web_news": data.web_news,
                "vacancies": data.web_vacancies,
                "sbar": data.sbar_data,
            }
            console.print(f"""ВЫВОД 1:
            {data.crm_products}""")
            data.crm_products = enrich_products_with_recommendations(
                products=data.crm_products,
                card_data=card_data_dict,
                company_name=company_name,
                meeting_topic=meeting_topic,
            )
            console.print(f"""ВЫВОД 2:
                        {data.crm_products}""")
            recommended_count = sum(1 for p in data.crm_products if p.get("recommended"))
            console.print(
                f"[green]   ✓ Рекомендовано {recommended_count} из {len(data.crm_products)} продуктов[/green]")
        except Exception as e:
            data.errors.append(f"Подбор продуктов: {e}")
            console.print(f"[yellow]   ⚠️ Подбор продуктов: fallback без LLM ({e})[/yellow]")
        progress.remove_task(task)

    # Закрываем соединения
    os_client.close()

    save_report = True

    if save_report:
        try:
            saved_file = data.save_to_markdown(
                'C:/Users/aasergeeva/Desktop/sales_project/sales-agent/card_information.md'
            )
            console.print(f"[green]✅ Отчет сохранен: {saved_file}[/green]")
        except Exception as e:
            console.print(f"[red]❌ Ошибка при сохранении отчета: {e}[/red]")
            data.errors.append(f"Сохранение отчета: {e}")

    return data
