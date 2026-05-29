# 🤖 Sales Agent — AI-агент для подготовки к встречам с клиентами

Автоматический сбор карточки клиента перед встречей: CRM, внутренняя база (Opensearch), WebSearch, аналитика. LangChain + GigaChat + FastAPI.

---

## 📋 Что делает агент

По названию компании (и/или ИНН) и теме встречи агент за 5–120 секунд:

1. **Ищет в OpenSearch** — находит клиента во внутренней базе (заметки, теги, рейтинг, история встреч)
2. **Ищет в CRM** — получает историю сделок, контакты, ЛПР, взаимодействия, каталог продуктов
3. **Ищет в интернете** — новости компании, руководство, сайт, вакансии, ИНН
4. **Запрашивает СБАР** — ОКВЭД, учредители, ЕГРЮЛ (если передан ИНН)
5. **Анализирует через LLM** — определяет боли, потребности, подбирает предложения, даёт советы к встрече

---

## 🏗️ Структура проекта

```
sales-agent/
├── api_server.py              # FastAPI сервер (:8900) — основной способ запуска
├── main.py                    # CLI-точка входа (командная строка)
├── config.py                  # Конфигурация из .env
├── db.py                      # SQLite-хранилище карточек (cards.db)
├── collect_card.py            # Скрипт сбора карточки (stdin → stdout)
│
├── agent/                     # Ядро агента
│   ├── agent.py               # Создание LLM (GigaChat) + run_pipeline()
│   ├── pipeline.py            # 8-шаговый детерминированный пайплайн сбора
│   ├── prompts.py             # Системные промпты для анализа
│   └── tools/                 # Инструменты LangChain @tool
│       ├── crm_tool.py        #   CRM — 6 инструментов
│       ├── opensearch_tool.py  #   OpenSearch — 1 инструмент
│       ├── websearch_tool.py   #   DuckDuckGo + чтение страниц — 6 инструментов
│       └── sbar_tool.py       #   СБАР (Sber Analytics) — 1 инструмент
│
├── crm/                       # Модуль CRM
│   ├── base.py                #   Абстрактный интерфейс CRMBase
│   ├── mock_crm.py            #   Моковая CRM (JSON-файл)
│   ├── mcp_server.py          #   MCP-сервер для CRM
│   └── data/
│       └── mock_data.json     #   Тестовые данные (11 компаний, 20 сделок)
│
├── opensearch/                # Модуль OpenSearch
│   ├── client.py              #   Клиент с автофоллбэком на JSON
│   ├── seed.py                #   Загрузка тестовых данных в OpenSearch
│   └── data/
│       └── clients_data.json  #   Тестовые данные (11 компаний)
│
├── utils/
│   └── web_reader.py          # Чтение веб-страниц (httpx + trafilatura)
│
├── requirements.txt           # Python-зависимости
└── .env                       # Переменные окружения (создать из примера ниже)
```

---

## 🛠️ Инструменты агента (14 штук)

### OpenSearch (1)
| Инструмент | Описание |
|---|---|
| `search_clients_db` | Поиск во внутренней базе клиентов по названию, ИНН, описанию, тегам, отрасли |

### CRM (6)
| Инструмент | Описание |
|---|---|
| `crm_get_client_info` | Полная карточка клиента из CRM |
| `crm_search_clients` | Поиск клиентов по названию |
| `crm_get_deals` | История сделок (суммы, статусы, даты) |
| `crm_get_contacts` | Контактные лица, ЛПР, должности |
| `crm_get_interactions` | История взаимодействий (звонки, встречи, письма) |
| `crm_get_our_products` | Каталог наших продуктов и услуг |

### Web Search (6)
| Инструмент | Описание |
|---|---|
| `web_search` | Общий поиск в DuckDuckGo |
| `web_search_news` | Поиск новостей компании |
| `read_web_page` | Чтение текста веб-страницы |
| `search_company_vacancies` | Вакансии компании |
| `search_company_leaders` | Руководство компании (+ чтение страниц) |
| `search_company_inn` | Поиск ИНН и юридической информации |

### СБАР — Sber Analytics (1)
| Инструмент | Описание |
|---|---|
| `sbar_search_by_inn` | ОКВЭД, учредители, ЕГРЮЛ по ИНН через СБАР API |

---

## ⚡ Два режима работы

### 1. Прямой сбор (`collect-direct`) — 5–15 секунд
Не требует LLM. Вызывает CRM + OpenSearch + DuckDuckGo + СБАР напрямую.

```
POST /api/agent/collect-direct
```

**Результат:** структурированные данные без анализа и рекомендаций.

### 2. Агентный сбор (`collect-card`) — 30–120 секунд
Сначала детерминированный пайплайн собирает данные, затем GigaChat анализирует.

```
POST /api/agent/collect-card
```

**Результат:** структурированные данные + `agentAnalysis` с анализом болей, потребностей и рекомендациями.

> Если GigaChat не настроен — автоматически переключается на прямой сбор.

---

## 🔀 Пайплайн сбора данных (8 шагов)

`agent/pipeline.py` реализует детерминированный порядок опроса источников:

| Шаг | Источник | Что собирает | Приоритет ИНН |
|-----|----------|-------------|---------------|
| 1 | OpenSearch | Внутренняя база клиентов | ✅ Сначала по ИНН |
| 2 | CRM | Клиент, сделки, контакты, взаимодействия | ✅ Сначала по ИНН |
| 3 | Каталог продуктов | Наши продукты с отраслевой привязкой | — |
| 4 | Web — общий | Информация о компании + ИНН | — |
| 5 | Web — новости | Новости + чтение статей | — |
| 6 | Web — руководство | ЛПР и руководство + чтение страниц | — |
| 7 | Web — вакансии | Актуальные вакансии | — |
| 8 | СБАР | ОКВЭД, учредители, ЕГРЮЛ | Требуется ИНН |

**INN-priority:** если передан ИНН, сначала ищем по точному совпадению, затем — по названию.

---

## 🚀 Установка и запуск

### 1. Клонировать и создать venv

```bash
cd sales-agent
python -m venv venv

# Windows:
venv\Scripts\activate

# Linux/Mac:
source venv/bin/activate
```

### 2. Установить зависимости

```bash
pip install -r requirements.txt
```

### 3. Создать файл .env

```bash
# Минимальный .env — работает без Docker и без GigaChat:
cp .env.example .env
```

Или создайте `.env` вручную:

```env
# ── GigaChat (опционально — для LLM-анализа) ──
GIGACHAT_CLIENT_ID=
GIGACHAT_CLIENT_SECRET=
GIGACHAT_SCOPE=GIGACHAT_API_PERS
GIGACHAT_MODEL=GigaChat-Pro

# ── OpenSearch (опционально — без Docker работает на JSON) ──
OPENSEARCH_HOST=localhost
OPENSEARCH_PORT=9200
OPENSEARCH_USE_SSL=false
OPENSEARCH_USER=admin
OPENSEARCH_PASSWORD=admin

# ── CRM ──
CRM_TYPE=mock

# ── Web Search ──
DDGS_PROXY=
WEB_READ_TIMEOUT=30
MAX_PAGES_TO_READ=5

# ── API Server ──
SALES_AGENT_PORT=8900
```

### 4. Запустить API сервер

```bash
python api_server.py
```

Сервер поднимется на **http://localhost:8900**

Проверка:
```bash
curl http://localhost:8900/health
# → {"status":"ok","service":"sales-agent-api","gigachat_configured":false}
```

## 📡 API Endpoints

Сервер запускается на `http://localhost:8900`

### Health

```
GET /health
```
```json
{
  "status": "ok",
  "service": "sales-agent-api",
  "gigachat_configured": false,
  "opensearch_mode": "json-fallback",
  "debug": false
}
```

### Быстрый сбор карточки (без LLM)

```
POST /api/agent/collect-direct
Content-Type: application/json

{
  "companyName": "ООО ТехноСфера",
  "meetingTopic": "Внедрение BI-аналитики",
  "inn": "7701234567"
}
```

**Время:** 5–15 сек. **LLM:** нет.

### Полный сбор карточки (с LLM)

```
POST /api/agent/collect-card
Content-Type: application/json

{
  "companyName": "ООО ТехноСфера",
  "meetingTopic": "Внедрение BI-аналитики",
  "inn": "7701234567"
}
```

**Время:** 30–120 сек. **LLM:** GigaChat-Pro (автофоллбэк на прямой, если не настроен).

### Структура ответа

```json
{
  "success": true,
  "data": {
    "companyName": "ООО \"ТехноСфера\"",
    "meetingTopic": "Внедрение BI-аналитики",
    "inn": "7701234567",

    "crm": {
      "clientInfo": { "id": "CL-001", "name": "...", "status": "active", "industry": "IT" },
      "deals": [ { "id": "DL-001", "name": "...", "amount": 3200000, "status": "won" } ],
      "contacts": [ { "name": "...", "position": "IT-директор", "isLPR": true } ],
      "interactions": [ { "type": "meeting", "date": "...", "notes": "..." } ]
    },

    "opensearch": [ { "id": "OS-001", "companyName": "...", "tags": [...], "internalRating": 8 } ],

    "webSearch": [ { "title": "...", "body": "...", "href": "..." } ],
    "webNews": [ { "title": "...", "body": "...", "date": "..." } ],
    "vacancies": [ { "title": "...", "body": "..." } ],

    "products": [ { "id": "PR-003", "name": "BI-Платформа", "category": "Аналитика" } ],

    "sbar": { "inn": "7701234567", "ogrn": "...", "okved": [...], "participants": [...] },

    "agentAnalysis": "# 📋 КАРТОЧКА КЛИЕНТА\n..."  // только с LLM
  },
  "elapsedSeconds": 12.3
}
```

### Сохранённые карточки (SQLite)

```
GET  /api/cards                              # Список всех карточек
GET  /api/cards?companyName=ООО+ТехноСфера   # Загрузить конкретную
DELETE /api/cards?companyName=ООО+ТехноСфера  # Удалить
```

---

## 💻 CLI-запуск

```bash
# Активировать venv
venv\Scripts\activate

# Запуск агента (нужен GigaChat)
python main.py "ООО ТехноСфера" "Внедрение BI-аналитики"

# Проверка подключений
python main.py --check

# Загрузка данных в OpenSearch
python main.py --seed

# Запуск MCP-сервера CRM
python main.py --mcp
```

## 🔌 Подключение к Electron (copilot-sales)

Агент интегрируется в Electron+Svelte десктопное приложение.

### Способ 1: Автозапуск из Electron (рекомендуется)

Python API запускается как дочерний процесс при старте Electron.

В `copilot-sales/electron/main.cjs`:

```javascript
const PYTHON_CMD = 'C:\\Users\\aasergeeva\\Desktop\\sales-agent\\venv\\Scripts\\python.exe';
const SALES_AGENT_DIR = 'C:\\Users\\aasergeeva\\Desktop\\sales-agent';

// ... spawn Python при старте, kill при закрытии
```

В `copilot-sales/vite.config.js`:

```javascript
proxy: {
  '/agent-api': {
    target: 'http://localhost:8900',
    changeOrigin: true,
    rewrite: (path) => path.replace(/^\/agent-api/, ''),
  },
}
```

Запуск: `npm run electron:dev`

### Способ 2: Ручной запуск + bat-файл

```cmd
:: Терминал 1 — API
cd C:\Users\aasergeeva\Desktop\sales-agent
venv\Scripts\activate
python api_server.py

:: Терминал 2 — Фронтенд
cd C:\Users\aasergeeva\Desktop\sales_manager\copilot-sales
npm run dev
```
---

## ⚙️ Конфигурация (.env)

| Переменная | По умолчанию | Описание |
|---|---|---|
| **GigaChat** | | |
| `GIGACHAT_API_KEY` | — | Альтернатива: API-ключ (вместо ID+Secret) |
| `GIGACHAT_SCOPE` | `GIGACHAT_API_PERS` | Scope: `GIGACHAT_API_PERS` или `GIGACHAT_API_B2B` |
| `GIGACHAT_MODEL` | `GigaChat-Pro` | Модель GigaChat |
| **OpenSearch** | | |
| `OPENSEARCH_HOST` | `localhost` | Хост OpenSearch |
| `OPENSEARCH_PORT` | `9200` | Порт OpenSearch |
| `OPENSEARCH_USE_SSL` | `true` | Использовать SSL |
| `OPENSEARCH_USER` | `admin` | Логин |
| `OPENSEARCH_PASSWORD` | `admin` | Пароль |
| `OPENSEARCH_VERIFY_CERTS` | `false` | Проверять SSL-сертификаты |
| **CRM** | | |
| `CRM_TYPE` | `mock` | Тип CRM: `mock` / `api` / `mcp` |
| `CRM_API_URL` | — | URL реальной CRM API |
| `CRM_API_KEY` | — | Ключ для CRM API |
| `CRM_MCP_URL` | — | URL MCP-сервера CRM |
| **Web Search** | | |
| `WEB_READ_TIMEOUT` | `30` | Таймаут загрузки страниц (сек) |
| `MAX_PAGES_TO_READ` | `5` | Макс. страниц для чтения за запрос |
| **API Server** | | |
| `SALES_AGENT_PORT` | `8900` | Порт FastAPI сервера |

---

## 📊 Тестовые данные

В проекте есть моковые данные для 11 компаний из 8 отраслей:

| Компания | Отрасль | Статус CRM | Сделки |
|---|---|---|---|
| ООО «ТехноСфера» | IT | active | 3 |
| АО «СтройИнвест» | Строительство | active | 2 |
| ООО «ЛогистикПро» | Логистика | prospect | 1 |
| ПАО «АльфаЭнерго» | Энергетика | active | 2 |
| ООО «МедТех» | Мед. оборудование | inactive | 2 |
| АО «РитейлГрупп» | Ритейл | active | 2 |
| ООО «ФинансКонсалтинг» | Фин. консалтинг | prospect | 2 |
| ГУП «МосТрансАвто» | Транспорт | active | 2 |
| ООО «РусТехСнаб» | Промышленность | prospect | 1 |
| ООО «СибирьЭнерго» | Энергетика | inactive | 2 |
| АО «АгроИнвест» | Сельское хозяйство | active | 1 |

- **20 сделок** (суммы: 680 000 – 18 500 000 ₽)
- **20 контактов** (с флагами ЛПР)
- **24 взаимодействия** (звонки, встречи, письма, задачи)
- **~10 продуктов** (CRM, BI, IoT, SOC, WMS, PM, Облачная АТС, Платформа лояльности и др.)

---

## 🔧 Решение проблем

### GigaChat возвращает ошибку авторизации
- Проверьте `GIGACHAT_API_KEY` в `.env`
- Убедитесь, что scope соответствует вашему тарифу

### DuckDuckGo не работает
- В России DuckDuckGo может блокироваться. Укажите прокси:
  ```env
  DDGS_PROXY=socks5://127.0.0.1:1080
  ```

### OpenSearch недоступен
- Проверить подключение тестового ВПН
- Агент автоматически переключается на моковый режим (JSON-файл)

### ModuleNotFoundError при запуске из Electron
- Electron запускает системный Python, а не venv
- Решение: укажите путь к venv-Python в `electron/main.cjs`:
  ```javascript
  const PYTHON_CMD = 'C:\\Users\\aasergeeva\\Desktop\\sales-agent\\venv\\Scripts\\python.exe';
  ```

### UnicodeEncodeError на Windows
- Добавьте переменные окружения в spawn:
  ```javascript
  env: {
    ...process.env,
    PYTHONIOENCODING: 'utf-8',
    PYTHONUTF8: '1',
  }
  ```

### Порт 8900 занят
```bash
# Windows
netstat -ano | findstr :8900
taskkill /PID <pid> /F

# Linux/Mac
lsof -i :8900
kill -9 <pid>
```

---

## 📐 Архитектура системы

```
┌─────────────────────────────┐
│   Пользователь              │
│   (CLI / Electron+Svelte)   │
└──────────────┬──────────────┘
               │
       ┌───────┴───────┐
       ▼               ▼
  ┌─────────┐    ┌───────────────────┐
  │ main.py │    │  api_server.py    │
  │  (CLI)  │    │  (FastAPI :8900)  │
  └────┬────┘    └────────┬──────────┘
       │                  │
       │     ┌────────────┼────────────┐
       │     ▼            ▼            ▼
       │  ┌───────┐  ┌────────┐  ┌──────────┐
       │  │ Прямой│  │Пайплайн│  │ Карточки │
       │  │ сбор  │  │  +LLM  │  │  (CRUD)  │
       │  └───┬───┘  └───┬────┘  └────┬─────┘
       │      │          │            │
       └──────┼──────────┼────────────┘
              │          │
     ┌────────┴──────────┴────────┐
     ▼         ▼         ▼        ▼
┌─────────┐ ┌─────┐ ┌───────┐ ┌──────┐
│OpenSearch│ │ CRM │ │DDGS   │ │ СБАР │
│(JSON/   │ │(mock│ │(Duck  │ │(Sber │
│ Docker) │ │/api)│ │DuckGo)│ │Analyt│
└─────────┘ └─────┘ └───────┘ └──────┘
                           │
                     ┌─────┴─────┐
                     │ web_reader │
                     │(httpx +    │
                     │trafilatura)│
                     └───────────┘
```
