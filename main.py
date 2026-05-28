"""Sales Agent — Агент-помощник менеджера по продажам.

Подготавливает карточку клиента перед встречей на основе данных
из OpenSearch, CRM и интернета.

Использование:
    python main.py "ООО ТехноСфера" "Внедрение CRM"
    python main.py --company "ООО ТехноСфера" --topic "Внедрение CRM"
"""

import argparse
import sys
import warnings
import json

from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown

# Подавление предупреждений
warnings.filterwarnings("ignore")


console = Console()


def parse_args() -> argparse.Namespace:
    """Парсинг аргументов командной строки."""
    parser = argparse.ArgumentParser(
        description="Sales Agent — Агент-помощник менеджера по продажам",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  python main.py "ООО ТехноСфера" "Внедрение CRM"
  python main.py --company "АО СтройИнвест" --topic "Облачная телефония"
  python main.py --seed     # Загрузить тестовые данные в OpenSearch
  python main.py --mcp      # Запустить MCP-сервер CRM
        """,
    )

    parser.add_argument(
        "--company", "-c",
        required=False,
        help="Название компании",
    )
    parser.add_argument(
        "--topic", "-t",
        default="Обсуждение сотрудничества",
        help="Тема встречи (по умолчанию: 'Обсуждение сотрудничества')",
    )
    parser.add_argument(
        "--inn",
        default="",
        help="ИНН компании (по умолчанию: 'Обсуждение сотрудничества')",
    )
    parser.add_argument(
        "--seed",
        action="store_true",
        help="Загрузить тестовые данные в OpenSearch",
    )
    parser.add_argument(
        "--mcp",
        action="store_true",
        help="Запустить MCP-сервер CRM",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Проверить подключение к OpenSearch и CRM",
    )

    return parser.parse_args()


def check_connections():
    """Проверка подключений к OpenSearch и CRM."""
    console.print("\n[bold]Проверка подключений...[/bold]\n")

    # Проверка OpenSearch
    console.print("[cyan]1. OpenSearch:[/cyan]")
    try:
        from opensearch.client import OpenSearchClient
        client = OpenSearchClient()
        connected = client.connect()
        if connected:
            console.print("   ✅ Подключено к OpenSearch")
        else:
            console.print("   ⚠️  Моковый режим (OpenSearch недоступен)")
        client.close()
    except Exception as e:
        console.print(f"   ❌ Ошибка: {e}")

    # Проверка CRM
    console.print("\n[cyan]2. CRM:[/cyan]")
    try:
        from crm.mock_crm import MockCRM
        crm = MockCRM()
        clients = crm.search_clients("")
        console.print(f"   ✅ CRM (mock) загружена, клиентов: {len(clients)}")
    except Exception as e:
        console.print(f"   ❌ Ошибка: {e}")

    # Проверка GigaChat
    console.print("\n[cyan]3. GigaChat:[/cyan]")
    try:
        import config
        if config.GIGACHAT_CLIENT_ID and config.GIGACHAT_CLIENT_SECRET:
            console.print("   ✅ Учётные данные GigaChat заданы")
        else:
            console.print("   ❌ Учётные данные GigaChat НЕ заданы. Укажите GIGACHAT_CLIENT_ID и GIGACHAT_CLIENT_SECRET в .env")
    except Exception as e:
        console.print(f"   ❌ Ошибка: {e}")

    # Проверка DuckDuckGo
    console.print("\n[cyan]4. DuckDuckGo Search:[/cyan]")
    try:
        from ddgs import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text("тест", max_results=1))
        if results:
            console.print("   ✅ DuckDuckGo Search работает")
        else:
            console.print("   ⚠️  DuckDuckGo Search не вернул результатов (возможно, блокировка)")
    except Exception as e:
        console.print(f"   ❌ Ошибка: {e}")

    console.print()


def seed_opensearch():
    """Загрузка тестовых данных в OpenSearch."""
    console.print("\n[bold]Загрузка тестовых данных в OpenSearch...[/bold]\n")
    from opensearch.seed import main as seed_main
    seed_main()


def run_mcp_server():
    """Запуск MCP-сервера CRM."""
    console.print("\n[bold]Запуск MCP-сервера CRM...[/bold]\n")
    console.print("Сервер запускается в режиме stdio.")
    console.print("Для подключения из другого процесса используйте MCP-клиент.\n")

    from crm.mcp_server import mcp
    mcp.run(transport="stdio")


def run_sales_agent(company_name: str, meeting_topic: str, inn: str=""):
    """Запуск агента для подготовки карточки клиента."""
    console.print()
    console.print(Panel.fit(
        f"[bold]🏢 Компания:[/bold] {company_name}\n"
        f"[bold]📋 Тема встречи:[/bold] {meeting_topic}",
        title="🤖 Sales Agent — Подготовка карточки клиента",
        border_style="blue",
    ))
    console.print()

    console.print("[dim]Двухфазный процесс:[/dim]")
    console.print("[dim]  1️⃣  Сбор данных: OpenSearch → CRM → Web Search[/dim]")
    console.print("[dim]  2️⃣  Анализ: GigaChat формирует карточку[/dim]")
    console.print()

    try:
        from agent.agent import run_agent, run_pipeline
        result = run_pipeline(company_name, meeting_topic, inn)

        console.print()

        console.print(Panel.fit(
            Markdown(result["raw_data"]),
            title="📋 Карточка клиента",
            border_style="green",
        ))

    except KeyboardInterrupt:
        console.print("\n[yellow]Прервано пользователем[/yellow]")
    except Exception as e:
        console.print(f"\n[red]Ошибка: {e}[/red]")
        import traceback
        console.print(f"\n[dim]{traceback.format_exc()}[/dim]")


def main():
    """Точка входа."""
    args = parse_args()

    # Определяем название компании
    company_name = args.company

    # Режим проверки подключений
    if args.check:
        check_connections()
        return

    inn = args.inn

    # Режим загрузки данных
    if args.seed:
        seed_opensearch()
        return

    # Режим MCP-сервера
    if args.mcp:
        run_mcp_server()
        return

    # Основной режим — запуск агента
    if not company_name:
        console.print("[red]Ошибка: укажите название компании[/red]")
        console.print("Использование: python main.py \"Название компании\" \"Тема встречи\"")
        console.print("Или: python main.py --company \"Название\" --topic \"Тема\"")
        sys.exit(1)

    meeting_topic = args.topic
    run_sales_agent(company_name, meeting_topic, inn)


if __name__ == "__main__":
    main()