"""Скрипт загрузки тестовых данных в OpenSearch.

Использование:
    python -m opensearch.seed          # Загрузить данные
    python -m opensearch.seed --reset  # Пересоздать индекс и загрузить данные
"""

import sys

from .client import OpenSearchClient


def main():
    reset = "--reset" in sys.argv

    client = OpenSearchClient()
    connected = client.connect()

    if not connected:
        print("\nДля загрузки данных необходим запущенный OpenSearch.")
        print("Запустите Docker: docker compose up -d opensearch")
        print("Или работайте в моковом режиме (данные загружаются автоматически).")
        return 0

    if reset:
        index = "clients"
        if client._client.indices.exists(index=index):
            client._client.indices.delete(index=index)
            print(f"✓ Индекс '{index}' удалён")

    # Создаём индекс с маппингом
    client.create_index()

    # Загружаем данные
    count = client.seed_data()
    print(f"\n✓ Готово! Загружено {count} документов.")

    client.close()


if __name__ == "__main__":
    main()