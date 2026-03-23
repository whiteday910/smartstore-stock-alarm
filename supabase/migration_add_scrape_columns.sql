-- 기존 프로젝트에 한 번만 실행 (SQL Editor)
ALTER TABLE public.monitors
  ADD COLUMN IF NOT EXISTS last_scrape_ok BOOLEAN,
  ADD COLUMN IF NOT EXISTS last_scrape_note TEXT,
  ADD COLUMN IF NOT EXISTS last_http_status INTEGER;
