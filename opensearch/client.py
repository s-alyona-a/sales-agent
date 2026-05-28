"""Клиент OpenSearch с поддержкой мокового режима (без Docker).

Если подключение к OpenSearch недоступно — автоматически используется
локальный поиск по JSON-файлу с тестовыми данными.

Поддержка INN-priority: при наличии ИНН поиск сначала по точному ИНН,
затем — fallback по названию компании.
"""

import json
from pathlib import Path
from typing import Any

from opensearchpy import OpenSearch
from opensearchpy.helpers import bulk

import config


class OpenSearchClient:
    """Клиент для работы с OpenSearch.

    Поддерживает два режима:
    1. Реальный OpenSearch (требуется Docker)
    2. Моковый режим (поиск по JSON-файлу)
    """

    def __init__(self):
        self._client: OpenSearch | None = None
        self._mock_data: list[dict] | None = None
        self._use_mock = False

    def connect(self, force_mock: bool = False) -> bool:
        """Подключение к OpenSearch. Возвращает True, если подключение успешно.

        Args:
            force_mock: Если True — пропустить попытку подключения и сразу
                        использовать моковый режим (избегает 5-секундного таймаута).
        """
        if force_mock:
            print("ℹ OpenSearch: принудительный моковый режим (force_mock=True)")
            self._use_mock = True
            self._load_mock_data()
            return False

        try:
            client = OpenSearch(
                hosts=[{"host": config.OPENSEARCH_HOST, "port": config.OPENSEARCH_PORT}],
                http_auth=(config.OPENSEARCH_USER, config.OPENSEARCH_PASSWORD),
                use_ssl=True,   # config.OPENSEARCH_USE_SSL,
                verify_certs=False,  # config.OPENSEARCH_VERIFY_CERTS,
                ssl_show_warn=False,
                timeout=50,
            )
            # info = client.info()
            print(f"✓ Подключено к OpenSearch: host: {config.OPENSEARCH_HOST}, port: {config.OPENSEARCH_PORT}")
            self._client = client
            self._use_mock = False
            return True
        except Exception as e:
            print(f"⚠ OpenSearch недоступен ({e}). Используем моковый режим.")
            self._use_mock = True
            self._load_mock_data()
            return False

    def _load_mock_data(self):
        """Загрузка моковых данных для локального поиска."""
        data_path = Path(__file__).parent / "data" / "clients_data.json"
        if data_path.exists():
            with open(data_path, "r", encoding="utf-8") as f:
                self._mock_data = json.load(f)
            print(f"✓ Загружено {len(self._mock_data)} записей из моковых данных")
        else:
            self._mock_data = []
            print("⚠ Моковые данные не найдены")

    # ──────────────────────────────────────────────
    #  Полнотекстовый поиск по названию / запросу
    # ──────────────────────────────────────────────

    def search(self, query: str, index: str | None = None, size: int = 10) -> list[dict[str, Any]]:
        """Полнотекстовый поиск по индексу клиентов.

        Args:
            query: Поисковый запрос (название компании, ИНН и т.д.).
            index: Имя индекса (по умолчанию из конфига).
            size: Максимальное количество результатов.

        Returns:
            Список найденных документов.
        """
        if index is None:
            index = config.OPENSEARCH_INDEX

        if self._use_mock:
            return self._mock_search(query, size)

        try:
            # Определяем, является ли запрос ИНН (только цифры, 10-12 символов)
            is_inn = query.isdigit() and len(query) in (10, 12)

            if is_inn:
                body = {
                    "size": size,
                    "query": {
                        "term": {
                            "inn": query  # ← строка, не int(query)
                        }
                    }
                }
            else:
                # Для названий компаний - полнотекстовый поиск без поля inn
                body = {
                    "size": size,
                    "query": {
                        "multi_match": {
                            "query": query,
                            "fields": [
                                "company_name^3",
                                "description^2",
                                "tags",
                                "notes",
                                "industry",
                                "okved_description",
                            ],
                            "fuzziness": "AUTO",
                        }
                    },
                    "highlight": {
                        "fields": {
                            "company_name": {},
                            "description": {},
                            "notes": {},
                        }
                    },
                }

            print(f"==== BODY SEARCH: {body} =====")

            response = self._client.search(body=body, index=index)

            print(f"RESPONSE: {response}")
            hits = response["hits"]["hits"]

            results = []
            for hit in hits:
                result = hit["_source"]
                result["_score"] = hit["_score"]
                if "highlight" in hit:
                    result["_highlights"] = hit["highlight"]
                results.append(result)

            return results

        except Exception as e:
            print(f"Ошибка поиска в OpenSearch: {e}")
            return self._mock_search(query, size)


    def _mock_search(self, query: str, size: int = 10) -> list[dict[str, Any]]:
        """Простой полнотекстовый поиск по моковым данным."""
        if not self._mock_data:
            return []

        query_lower = query.lower()
        results = []

        for doc in self._mock_data:
            score = 0
            # Поиск по всем текстовым полям
            searchable_fields = [
                "company_name", "inn", "description", "notes",
                "industry", "okved", "okved_description", "tags",
            ]
            for field in searchable_fields:
                value = doc.get(field, "")
                if isinstance(value, list):
                    value = " ".join(str(v) for v in value)
                value_lower = str(value).lower()
                if query_lower in value_lower:
                    # Больше вес для названия компании
                    if field == "company_name":
                        score += 10
                    elif field == "inn":
                        score += 8
                    elif field == "description":
                        score += 5
                    else:
                        score += 3

            if score > 0:
                doc_copy = dict(doc)
                doc_copy["_score"] = score
                results.append(doc_copy)

        # Сортировка по релевантности
        results.sort(key=lambda x: x.get("_score", 0), reverse=True)
        return results[:size]

    # ──────────────────────────────────────────────
    #  Поиск по ИНН (INN-priority)
    # ──────────────────────────────────────────────

    def search_by_inn(self, inn: str, index: str | None = None, size: int = 1) -> dict[str, Any] | None:
        """Точный поиск по ИНН."""
        if not inn:
            return None

        if index is None:
            index = config.OPENSEARCH_INDEX

        if self._use_mock:
            return self._mock_search_by_inn(inn)

        try:
            # ИНН должен быть строкой, т.к. в маппинге тип keyword
            body = {
                "size": size,
                "query": {
                    "term": {
                        "inn": inn,  # ← строка, не int
                    }
                },
            }
            print(f"BODY INN: {body}")
            response = self._client.search(body=body, index=index)
            hits = response["hits"]["hits"]

            if hits:
                result = hits[0]["_source"]
                result["_score"] = hits[0]["_score"]
                return result

            return None

        except Exception as e:
            print(f"Ошибка поиска по ИНН в OpenSearch: {e}")
            return self._mock_search_by_inn(inn)

    def _mock_search_by_inn(self, inn: str) -> dict[str, Any] | None:
        """Поиск по ИНН в моковых данных (точное совпадение)."""
        if not self._mock_data:
            return None

        inn_str = str(inn).strip()
        for doc in self._mock_data:
            doc_inn = str(doc.get("inn", "")).strip()
            if doc_inn == inn_str:
                doc_copy = dict(doc)
                doc_copy["_score"] = 100  # точное совпадение → максимальный score
                return doc_copy

        return None

    # ──────────────────────────────────────────────
    #  Управление индексом
    # ──────────────────────────────────────────────

    def create_index(self, index: str | None = None) -> bool:
        """Создание индекса с маппингом для клиентских данных."""
        if self._use_mock or self._client is None:
            print("Моковый режим: создание индекса не требуется")
            return True

        if index is None:
            index = config.OPENSEARCH_INDEX

        mapping = {
            "settings": {
                "number_of_shards": 1,
                "number_of_replicas": 0,
                "analysis": {
                    "analyzer": {
                        "russian_analyzer": {
                            "type": "custom",
                            "tokenizer": "standard",
                            "filter": ["lowercase", "russian_stop", "russian_stemmer"],
                        }
                    },
                    "filter": {
                        "russian_stop": {"type": "stop", "stopwords": "_russian_"},
                        "russian_stemmer": {"type": "stemmer", "language": "russian"},
                    },
                },
            },
            "mappings": {
                "properties": {
                    "company_name": {"type": "text", "analyzer": "russian_analyzer", "boost": 3},
                    "inn": {"type": "keyword", "boost": 2},
                    "description": {"type": "text", "analyzer": "russian_analyzer"},
                    "industry": {"type": "text", "analyzer": "russian_analyzer"},
                    "okved": {"type": "keyword"},
                    "okved_description": {"type": "text", "analyzer": "russian_analyzer"},
                    "website": {"type": "keyword"},
                    "tags": {"type": "text", "analyzer": "russian_analyzer"},
                    "notes": {"type": "text", "analyzer": "russian_analyzer"},
                    "region": {"type": "keyword"},
                    "employee_count": {"type": "integer"},
                    "revenue": {"type": "long"},
                    "last_meeting_date": {"type": "date", "format": "yyyy-MM-dd"},
                    "internal_rating": {"type": "integer"},
                }
            },
        }

        try:
            if self._client.indices.exists(index=index):
                print(f"Индекс '{index}' уже существует")
                return True

            self._client.indices.create(index=index, body=mapping)
            print(f"✓ Индекс '{index}' создан")
            return True
        except Exception as e:
            print(f"Ошибка создания индекса: {e}")
            return False

    def seed_data(self, data_path: str | Path | None = None) -> int:
        """Загрузка тестовых данных в OpenSearch.

        Args:
            data_path: Путь к JSON-файлу с данными.

        Returns:
            Количество загруженных документов.
        """
        if self._use_mock or self._client is None:
            print("Моковый режим: загрузка данных в OpenSearch не требуется")
            return 0

        if data_path is None:
            data_path = Path(__file__).parent / "data" / "clients_data.json"

        data_path = Path(data_path)
        if not data_path.exists():
            print(f"Файл с данными не найден: {data_path}")
            return 0

        with open(data_path, "r", encoding="utf-8") as f:
            documents = json.load(f)

        index = config.OPENSEARCH_INDEX

        # Убедимся, что индекс существует
        self.create_index(index)

        # Подготовка данных для bulk-загрузки
        actions = []
        for i, doc in enumerate(documents):
            action = {
                "_index": index,
                "_id": doc.get("id", f"doc-{i}"),
                "_source": doc,
            }
            actions.append(action)

        # Загрузка
        success, errors = bulk(self._client, actions, raise_on_error=False)

        if errors:
            print(f"⚠ Загружено {success} из {len(actions)} документов. Ошибки: {errors[:3]}")
        else:
            print(f"✓ Загружено {success} документов в индекс '{index}'")

        return success

    def close(self):
        """Закрытие соединения с OpenSearch."""
        if self._client is not None:
            self._client.close()