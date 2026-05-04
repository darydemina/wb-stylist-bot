-- =====================================================
-- WB Stylist Bot — схема БД для Supabase
-- Выполни весь скрипт целиком в SQL Editor
-- =====================================================

-- USERS: основная таблица пользователей
CREATE TABLE IF NOT EXISTS users (
    telegram_id           BIGINT PRIMARY KEY,
    username              TEXT,
    created_at            TIMESTAMPTZ DEFAULT NOW(),
    onboarded             BOOLEAN DEFAULT FALSE,
    tryons_used           INTEGER DEFAULT 0,
    avatar_url            TEXT,
    canonical_photo_url   TEXT,
    profile_json          JSONB,
    stylist_summary       TEXT,
    last_active_at        TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_onboarded ON users(onboarded);
CREATE INDEX IF NOT EXISTS idx_users_last_active ON users(last_active_at DESC);

-- USER_PHOTOS: история всех присланных фото
CREATE TABLE IF NOT EXISTS user_photos (
    id           BIGSERIAL PRIMARY KEY,
    telegram_id  BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
    photo_url    TEXT NOT NULL,
    is_active    BOOLEAN DEFAULT TRUE,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_user_photos_tg ON user_photos(telegram_id);
CREATE INDEX IF NOT EXISTS idx_user_photos_active ON user_photos(telegram_id, is_active);

-- PROFILE_HISTORY: архив старых моделей при /update_photo
CREATE TABLE IF NOT EXISTS profile_history (
    id                       BIGSERIAL PRIMARY KEY,
    telegram_id              BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
    old_avatar_url           TEXT,
    old_profile_json         JSONB,
    old_canonical_photo_url  TEXT,
    old_stylist_summary      TEXT,
    archived_at              TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_profile_history_tg ON profile_history(telegram_id);

-- TRYONS: история всех примерок
CREATE TABLE IF NOT EXISTS tryons (
    id              BIGSERIAL PRIMARY KEY,
    telegram_id     BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
    type            TEXT NOT NULL CHECK (type IN ('look', 'item')),
    wb_urls         TEXT[] NOT NULL,
    items_data      JSONB NOT NULL,
    result_url      TEXT,
    verdict         TEXT,
    cost_estimate   NUMERIC(8, 4),
    success         BOOLEAN DEFAULT FALSE,
    error_message   TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tryons_tg ON tryons(telegram_id, created_at DESC);

-- FILLER_ITEMS: база базовых вещей для дополнения «примерь одну вещь»
CREATE TABLE IF NOT EXISTS filler_items (
    id           BIGSERIAL PRIMARY KEY,
    category     TEXT NOT NULL CHECK (category IN ('top', 'bottom', 'shoes', 'outer')),
    subcategory  TEXT NOT NULL,
    photo_url    TEXT NOT NULL,
    color        TEXT NOT NULL,
    color_temp   TEXT CHECK (color_temp IN ('warm', 'cool', 'neutral')),
    gender       TEXT NOT NULL CHECK (gender IN ('male', 'female', 'unisex')),
    description  TEXT,
    is_active    BOOLEAN DEFAULT TRUE,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_filler_active ON filler_items(category, gender, is_active);

-- PAYMENTS: история платежей через Telegram Stars
CREATE TABLE IF NOT EXISTS payments (
    id                    BIGSERIAL PRIMARY KEY,
    telegram_id           BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
    amount_stars          INTEGER NOT NULL,
    purpose               TEXT NOT NULL,
    telegram_payment_id   TEXT,
    invoice_payload       TEXT,
    created_at            TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_payments_tg ON payments(telegram_id, created_at DESC);

-- =====================================================
-- ROW LEVEL SECURITY (для public Supabase)
-- На MVP отключаем RLS т.к. ходим через service key из бэкенда.
-- Если переходишь на anon key — включи RLS и сделай policies.
-- =====================================================

ALTER TABLE users DISABLE ROW LEVEL SECURITY;
ALTER TABLE user_photos DISABLE ROW LEVEL SECURITY;
ALTER TABLE profile_history DISABLE ROW LEVEL SECURITY;
ALTER TABLE tryons DISABLE ROW LEVEL SECURITY;
ALTER TABLE filler_items DISABLE ROW LEVEL SECURITY;
ALTER TABLE payments DISABLE ROW LEVEL SECURITY;
