# 👗 WB Stylist Bot — Telegram-бот «AI-стилист с Wildberries»

MVP персонального стилиста: пользователь присылает свои фото → бот создаёт AI-модель и анализирует стиль → пользователь шлёт ссылки на товары с Wildberries → бот примеряет вещи на модель и даёт вердикт.

## 🏗️ Архитектура

```
Telegram ↔ python-telegram-bot ↔ Python-бот (этот проект)
                                        ↓
                                   ├─→ Supabase (БД + Storage)
                                   ├─→ Wildberries API (парсинг товаров)
                                   ├─→ Gemini Vision (валидация фото + анализ профиля)
                                   ├─→ Gemini 2.5 Flash Image (генерация аватара)
                                   ├─→ FASHN.AI (виртуальная примерка)
                                   └─→ OpenAI GPT-4o-mini (тексты стилиста)
```

## 📋 Что нужно перед стартом

1. **Аккаунт Telegram** + созданный бот через [@BotFather](https://t.me/BotFather) → получить `BOT_TOKEN`
2. **Аккаунт Supabase** (бесплатный) — [supabase.com](https://supabase.com)
3. **Google AI Studio** — [aistudio.google.com](https://aistudio.google.com) → API key для Gemini
4. **FASHN.AI** — [fashn.ai](https://fashn.ai) → регистрация, API key (есть бесплатные кредиты)
5. **OpenAI** — [platform.openai.com](https://platform.openai.com) → API key (минимальный депозит $5)

## 🚀 Развёртывание на Replit

### Шаг 1. Создай Repl
1. Зайди на [replit.com](https://replit.com) → **Create Repl** → язык **Python**
2. Назови `wb-stylist-bot`

### Шаг 2. Залей код
1. Скопируй все файлы проекта в Repl (через UI или git)
2. В терминале Replit:
   ```bash
   pip install -r requirements.txt
   ```

### Шаг 3. Создай Supabase проект
1. На [supabase.com](https://supabase.com) → **New Project**
2. После создания зайди в **SQL Editor** → выполни скрипт из `db/schema.sql` (см. ниже)
3. В **Storage** создай 2 bucket-а:
   - `user-photos` — public, для фото юзеров
   - `avatars` — public, для сгенерированных аватаров
   - `tryon-results` — public, для результатов примерок
4. Получи URL и anon key из **Settings → API**

### Шаг 4. Добавь Secrets
В Replit открой вкладку **🔒 Secrets** (слева) и добавь:

| Ключ | Значение |
|---|---|
| `BOT_TOKEN` | от @BotFather |
| `SUPABASE_URL` | из Supabase Settings → API |
| `SUPABASE_KEY` | anon public key из Supabase |
| `GEMINI_API_KEY` | из Google AI Studio |
| `FASHN_API_KEY` | из fashn.ai |
| `OPENAI_API_KEY` | из platform.openai.com |
| `OWNER_TELEGRAM_ID` | твой Telegram ID (узнай у @userinfobot) |
| `FREE_TRYON_LIMIT` | `3` |
| `UPDATE_PHOTO_PRICE_STARS` | `99` |

### Шаг 5. Залей filler-вещи
Запусти один раз скрипт инициализации базовых вещей:
```bash
python -m scripts.seed_filler_items
```
Он зальёт 17 базовых предметов одежды в таблицу `filler_items`.

> ⚠️ Сейчас фото-заглушки (placeholder). Замени URL в `db/filler_items_seed.json` на реальные фото вещей с белым фоном для качественной примерки.

### Шаг 6. Запусти
```bash
python main.py
```

Если в Replit нужен always-on — подключи **Reserved VM** ($7/мес) в настройках Repl.

### Шаг 7. Тестируй
1. Открой своего бота в Telegram → `/start`
2. Пришли 2-4 фото
3. Получи аватар и анализ профиля
4. Пришли ссылку с WB → примерка

## 📁 Структура проекта

```
wb_stylist_bot/
├── main.py                       # Точка входа, регистрация хэндлеров
├── handlers/
│   ├── start.py                  # /start, онбординг, валидация фото
│   ├── tryon.py                  # Примерка лука и одной вещи
│   ├── profile.py                # /profile, /update_photo
│   └── payments.py               # Telegram Stars
├── services/
│   ├── supabase_client.py        # Все операции с БД и Storage
│   ├── wb_parser.py              # Парсинг Wildberries
│   ├── vision.py                 # Gemini: валидация + анализ профиля
│   ├── avatar.py                 # Gemini Image: генерация аватара
│   ├── tryon_api.py              # FASHN.AI try-on
│   ├── stylist.py                # GPT-4o-mini вердикты
│   └── filler_items.py           # Подбор дополнений из базы
├── utils/
│   ├── keyboards.py              # Все клавиатуры
│   ├── messages.py               # Все тексты ответов (русские)
│   ├── states.py                 # Enum состояний ConversationHandler
│   └── config.py                 # Загрузка переменных окружения
├── db/
│   ├── schema.sql                # SQL для создания таблиц
│   └── filler_items_seed.json    # База базовых вещей для дополнения
├── scripts/
│   └── seed_filler_items.py      # Заливка filler_items в БД
├── requirements.txt
├── .env.example
└── README.md
```

## 🛠️ Команды бота

| Команда | Действие |
|---|---|
| `/start` | Запуск, онбординг |
| `/help` | Помощь |
| `/profile` | Показать AI-модель и профиль |
| `/update_photo` | Обновить фото (платно: 99⭐) |
| `/reset` | Сбросить onboarding (для тестов, только для OWNER) |
| `/privacy` | Политика приватности |

## 💸 Экономика одного юзера (примерно)

| Этап | Цена |
|---|---|
| Онбординг (1 раз) | ~$0.05 |
| Одна примерка вещи | ~$0.05-0.10 |
| Один лук (3-4 вещи) | ~$0.15-0.30 |
| **3 бесплатные примерки** | **~$0.50** |

## ⚠️ Известные ограничения MVP

- Парсер WB опирается на их внутренний API → может сломаться при изменениях
- Filler-вещи — фиксированный набор, не из WB
- Try-on chain накапливает артефакты после 4-й вещи
- Нет защиты от спама (rate-limiting)
- История примерок не показывается в UI

## 🐛 Дебаг

Логи в stdout (Replit Console). Включи DEBUG-режим в `utils/config.py` для подробностей.

Если что-то сломалось:
1. Проверь все Secrets на месте
2. Проверь, что таблицы созданы в Supabase (SQL: `SELECT * FROM users LIMIT 1`)
3. Проверь, что bucket-ы public
4. Смотри stdout для traceback

## 📜 Лицензия

MIT для скелета. Используешь на свой риск.
