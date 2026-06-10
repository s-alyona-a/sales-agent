"""Моковая реализация CRM на основе JSON-файла.

Используется для локальной разработки и тестирования.
При подключении реальной CRM достаточно заменить этот модуль.
"""

import json
from pathlib import Path
from typing import Any

from .base import CRMBase


class MockCRM(CRMBase):
    """CRM-система с моковыми данными из JSON-файла."""

    def __init__(self, data_path: Path | str | None = None):
        if data_path is None:
            data_path = Path(__file__).parent / "data" / "mock_data.json"

        print(f"PATH 1: {data_path}")
        data_path = Path(__file__).parent / data_path
        print(f"PATH 2: {data_path}")
        self._data_path = Path(data_path)
        self._data = self._load_data()

    def _load_data(self) -> dict:
        """Загрузка данных из JSON-файла."""
        if not self._data_path.exists():
            raise FileNotFoundError(
                f"Файл с моковыми данными CRM не найден: {self._data_path}"
            )
        with open(self._data_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _find_client_by_name(self, company_name: str) -> dict | None:
        """Поиск клиента по названию (регистронезависимый, частичное совпадение)."""
        import re
        # Нормализация: убираем кавычки, лишние пробелы
        query_normalized = re.sub(r'["\"«»\']', '', company_name).strip().lower()
        clients = self._data.get("clients", [])

        # Сначала пробуем точное совпадение (без кавычек)
        for client in clients:
            client_normalized = re.sub(r'["\"«»\']', '', client["name"]).strip().lower()
            if client_normalized == query_normalized:
                return client

        # Затем частичное совпадение
        for client in clients:
            client_normalized = re.sub(r'["\"«»\']', '', client["name"]).strip().lower()
            if query_normalized in client_normalized or client_normalized in query_normalized:
                return client

        # Поиск по ключевым словам (для случая "ТехноСфера" → "ООО ТехноСфера")
        query_words = [w for w in query_normalized.split() if len(w) > 3]
        best_match = None
        best_score = 0
        for client in clients:
            client_normalized = re.sub(r'["\"«»\']', '', client["name"]).strip().lower()
            score = sum(1 for w in query_words if w in client_normalized)
            if score > best_score:
                best_score = score
                best_match = client

        if best_match and best_score > 0:
            return best_match

        return None

    def _find_client_by_inn(self, inn: str) -> dict | None:
        """Поиск клиента по ИНН (точное совпадение)."""
        inn_clean = inn.strip()
        clients = self._data.get("clients", [])
        for client in clients:
            if client.get("inn", "").strip() == inn_clean:
                return client
        return None

    def get_client_by_inn(self, inn: str) -> dict[str, Any] | None:
        """Получить карточку клиента по ИНН."""
        client = self._find_client_by_inn(inn)
        if client is None:
            return None
        return {
            "id": client["id"],
            "name": client["name"],
            "inn": client.get("inn", ""),
            "website": client.get("website", ""),
            "industry": client.get("industry", ""),
            "okved": client.get("okved", ""),
            "status": client.get("status", ""),
            "description": client.get("description", ""),
            "created_at": client.get("created_at", ""),
            "updated_at": client.get("updated_at", ""),
        }

    def get_client_info(self, company_name: str) -> dict[str, Any] | None:
        client = self._find_client_by_name(company_name)
        if client is None:
            return None
        # Возвращаем карточку без вложенных данных (сделки/контакты отдельно)
        return {
            "id": client["id"],
            "name": client["name"],
            "inn": client.get("inn", ""),
            "website": client.get("website", ""),
            "industry": client.get("industry", ""),
            "okved": client.get("okved", ""),
            "status": client.get("status", ""),
            "description": client.get("description", ""),
            "created_at": client.get("created_at", ""),
            "updated_at": client.get("updated_at", ""),
        }

    def get_deals(self, client_id: str) -> list[dict[str, Any]]:
        deals = self._data.get("deals", [])
        return [d for d in deals if d.get("client_id") == client_id]

    def get_contacts(self, client_id: str) -> list[dict[str, Any]]:
        contacts = self._data.get("contacts", [])
        return [c for c in contacts if c.get("client_id") == client_id]

    def get_interaction_history(self, client_id: str) -> list[dict[str, Any]]:
        history = self._data.get("interactions", [])
        return [h for h in history if h.get("client_id") == client_id]

    def search_clients(self, query: str) -> list[dict[str, Any]]:
        query_lower = query.lower().strip()
        clients = self._data.get("clients", [])
        results = []
        for client in clients:
            name_lower = client["name"].lower()
            inn = client.get("inn", "")
            if query_lower in name_lower or query_lower in inn:
                results.append({
                    "id": client["id"],
                    "name": client["name"],
                    "inn": client.get("inn", ""),
                    "industry": client.get("industry", ""),
                    "status": client.get("status", ""),
                })
        return results

    def get_our_products(self) -> list[dict[str, Any]]:
        return self._data.get("products", [])
