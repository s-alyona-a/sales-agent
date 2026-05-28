"""SQLite хранилище карточек клиентов.

Карточки сохраняются по ключу company_name (upsert).
Файл БД: cards.db в директории sales-agent.
"""

import json
import sqlite3
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).parent / "cards.db"


def _get_conn() -> sqlite3.Connection:
    """Получить соединение с БД (с автосозданием таблицы)."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    # ⚡ Гарантируем, что таблица существует при ЛЮБОМ обращении
    conn.execute("""
        CREATE TABLE IF NOT EXISTS client_cards (
            company_name    TEXT PRIMARY KEY,
            meeting_topic   TEXT DEFAULT '',
            card_data       TEXT DEFAULT '{}',
            agent_analysis  TEXT DEFAULT '',
            has_llm_analysis INTEGER DEFAULT 0,
            created_at      TEXT DEFAULT (datetime('now')),
            updated_at      TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    return conn


def init_db():
    """Создать таблицу, если не существует. Вызывается при старте сервера."""
    conn = _get_conn()
    conn.close()


def upsert_card(
    company_name: str,
    meeting_topic: str = "",
    card_data: dict | None = None,
    agent_analysis: str = "",
    has_llm: bool = False,
) -> None:
    """Вставить или обновить карточку компании."""
    conn = _get_conn()
    card_json = json.dumps(card_data or {}, ensure_ascii=False, default=str)
    conn.execute("""
        INSERT INTO client_cards (company_name, meeting_topic, card_data, agent_analysis, has_llm_analysis, updated_at)
        VALUES (?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(company_name) DO UPDATE SET
            meeting_topic   = excluded.meeting_topic,
            card_data       = excluded.card_data,
            agent_analysis  = excluded.agent_analysis,
            has_llm_analysis = excluded.has_llm_analysis,
            updated_at      = datetime('now')
    """, (company_name, meeting_topic, card_json, agent_analysis, int(has_llm)))
    conn.commit()
    conn.close()


def get_card(company_name: str) -> dict[str, Any] | None:
    """Получить карточку по названию компании."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM client_cards WHERE company_name = ?", (company_name,)
    ).fetchone()
    conn.close()
    if row is None:
        return None
    return dict(row)


def list_cards() -> list[dict[str, Any]]:
    """Список всех сохранённых карточек."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT company_name, meeting_topic, has_llm_analysis, updated_at FROM client_cards ORDER BY updated_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_card(company_name: str) -> bool:
    """Удалить карточку по названию компании. Возвращает True, если удалено."""
    conn = _get_conn()
    cursor = conn.execute(
        "DELETE FROM client_cards WHERE company_name = ?", (company_name,)
    )
    conn.commit()
    deleted = cursor.rowcount > 0
    conn.close()
    return deleted