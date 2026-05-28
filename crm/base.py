"""Абстрактный интерфейс CRM — базовый класс для любых реализаций.

При подключении реальной CRM достаточно создать класс-наследник,
реализующий все абстрактные методы, и указать его в CRM_TYPE.
"""

from abc import ABC, abstractmethod
from typing import Any


class CRMBase(ABC):
    """Базовый интерфейс CRM-системы.

    Все методы возвращают dict или list[dict] с данными.
    Конкретная реализация решает, откуда брать данные (API, БД, файл и т.д.).
    """

    @abstractmethod
    def get_client_info(self, company_name: str) -> dict[str, Any] | None:
        """Получить карточку клиента по названию компании.

        Args:
            company_name: Название компании (точное или частичное совпадение).

        Returns:
            Словарь с информацией о клиенте или None, если не найден.
            Ожидаемые поля:
            - id: str — идентификатор клиента в CRM
            - name: str — название компании
            - inn: str — ИНН
            - website: str — сайт
            - industry: str — отрасль
            - status: str — статус клиента (active/inactive/prospect)
            - created_at: str — дата создания карточки
            - updated_at: str — дата последнего обновления
        """

    @abstractmethod
    def get_client_by_inn(self, inn: str) -> dict[str, Any] | None:
        """Получить карточку клиента по ИНН (точное совпадение).

        Args:
            inn: ИНН компании.

        Returns:
            Словарь с информацией о клиенте или None.
            Поля те же, что у get_client_info.
        """

    @abstractmethod
    def get_deals(self, client_id: str) -> list[dict[str, Any]]:
        """Получить список сделок клиента.

        Args:
            client_id: Идентификатор клиента в CRM.

        Returns:
            Список словарей со сделками. Ожидаемые поля:
            - id: str — идентификатор сделки
            - client_id: str — идентификатор клиента
            - title: str — название сделки
            - status: str — статус (won/lost/in_progress/negotiation)
            - amount: float — сумма сделки
            - products: list[str] — список проданных товаров/услуг
            - created_at: str — дата создания
            - closed_at: str | None — дата закрытия
            - description: str — описание
        """

    @abstractmethod
    def get_contacts(self, client_id: str) -> list[dict[str, Any]]:
        """Получить список контактных лиц клиента.

        Args:
            client_id: Идентификатор клиента в CRM.

        Returns:
            Список словарей с контактами. Ожидаемые поля:
            - id: str — идентификатор контакта
            - client_id: str — идентификатор клиента
            - name: str — ФИО
            - position: str — должность
            - email: str — email
            - phone: str — телефон
            - is_lpr: bool — является ли ЛПР (лицом, принимающим решения)
            - last_contact_date: str | None — дата последнего контакта
            - notes: str — заметки
        """

    @abstractmethod
    def get_interaction_history(self, client_id: str) -> list[dict[str, Any]]:
        """Получить историю взаимодействий с клиентом.

        Args:
            client_id: Идентификатор клиента в CRM.

        Returns:
            Список словарей с взаимодействиями. Ожидаемые поля:
            - id: str — идентификатор взаимодействия
            - client_id: str — идентификатор клиента
            - type: str — тип (call/meeting/email/task)
            - date: str — дата
            - manager: str — ФИО менеджера
            - description: str — описание/результат
            - outcome: str — итог взаимодействия
        """

    @abstractmethod
    def search_clients(self, query: str) -> list[dict[str, Any]]:
        """Поиск клиентов по названию или ИНН.

        Args:
            query: Поисковый запрос (название компании или ИНН).

        Returns:
            Список найденных клиентов (упрощённые карточки).
        """

    @abstractmethod
    def get_our_products(self) -> list[dict[str, Any]]:
        """Получить каталог наших продуктов/услуг.

        Returns:
            Список продуктов. Ожидаемые поля:
            - id: str — идентификатор продукта
            - name: str — название
            - category: str — категория
            - description: str — описание
            - target_industries: list[str] — целевые отрасли
        """
