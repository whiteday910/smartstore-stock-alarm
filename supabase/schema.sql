-- ============================================================
-- 스마트스토어 재입고 알리미 — Supabase 스키마
-- Supabase 대시보드 > SQL Editor 에 붙여넣고 실행하세요.
-- ============================================================

CREATE TABLE IF NOT EXISTS public.monitors (
    id                 UUID        DEFAULT gen_random_uuid()  PRIMARY KEY,
    email              TEXT        NOT NULL,
    url                TEXT        NOT NULL,
    product_name       TEXT,
    last_status        TEXT        NOT NULL DEFAULT 'UNKNOWN'
                                   CHECK (last_status IN ('IN_STOCK','OUT_OF_STOCK','UNKNOWN','ERROR')),
    last_checked_at    TIMESTAMPTZ,
    last_scrape_ok     BOOLEAN,
    last_scrape_note   TEXT,
    last_http_status   INTEGER,
    notified_at        TIMESTAMPTZ,
    is_active          BOOLEAN     NOT NULL DEFAULT TRUE,
    unsubscribe_token  UUID        NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 활성 모니터 검색 최적화
CREATE INDEX IF NOT EXISTS idx_monitors_active
    ON public.monitors (is_active)
    WHERE is_active = TRUE;

-- 이메일 + URL 중복 방지 (활성 상태인 경우만)
CREATE UNIQUE INDEX IF NOT EXISTS idx_monitors_email_url_active
    ON public.monitors (email, url)
    WHERE is_active = TRUE;

-- unsubscribe_token 검색
CREATE INDEX IF NOT EXISTS idx_monitors_unsubscribe_token
    ON public.monitors (unsubscribe_token);

-- ── Row Level Security ──────────────────────────────────────
ALTER TABLE public.monitors ENABLE ROW LEVEL SECURITY;

-- 외부에서 직접 접근 불가 (서비스 롤 키로만 접근)
-- Next.js API routes 및 Python 스크립트는 service_role 키를 사용합니다.
CREATE POLICY "service_role_only" ON public.monitors
    FOR ALL
    USING (auth.role() = 'service_role');
