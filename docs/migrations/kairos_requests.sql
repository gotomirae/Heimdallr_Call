-- PRD Ref: §8 · Heimdallr Telegram → Kairos handoff
-- Apply once in the Heimdallr Supabase SQL Editor before deploying the listener.
CREATE TABLE IF NOT EXISTS public.kairos_requests (
  update_id BIGINT PRIMARY KEY,
  chat_id BIGINT NOT NULL,
  user_id BIGINT NOT NULL,
  request_kind TEXT NOT NULL DEFAULT 'company'
    CHECK (request_kind IN ('company', 'industry')),
  target_name TEXT NOT NULL,
  code TEXT REFERENCES public.krx_universe(code),
  company_name TEXT,
  raw_text TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'working', 'awaiting_input', 'rejected', 'failed', 'sending', 'sent', 'uncertain')),
  notion_url TEXT,
  industry TEXT,
  telegram_message_id BIGINT,
  drive_folder_name TEXT,
  drive_folder_url TEXT,
  drive_folder_confirmed BOOLEAN NOT NULL DEFAULT FALSE,
  confirmation_message_id BIGINT,
  confirmation_response TEXT,
  confirmation_responded_at TIMESTAMPTZ,
  error TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  claimed_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ
);

-- 기존 기업 전용 테이블을 기업·산업 공용 계약으로 안전하게 확장한다.
ALTER TABLE public.kairos_requests
  ADD COLUMN IF NOT EXISTS request_kind TEXT DEFAULT 'company',
  ADD COLUMN IF NOT EXISTS target_name TEXT,
  ADD COLUMN IF NOT EXISTS drive_folder_name TEXT,
  ADD COLUMN IF NOT EXISTS drive_folder_url TEXT,
  ADD COLUMN IF NOT EXISTS drive_folder_confirmed BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS confirmation_message_id BIGINT,
  ADD COLUMN IF NOT EXISTS confirmation_response TEXT,
  ADD COLUMN IF NOT EXISTS confirmation_responded_at TIMESTAMPTZ;
UPDATE public.kairos_requests
SET request_kind = COALESCE(request_kind, 'company'),
    target_name = COALESCE(target_name, company_name, industry)
WHERE request_kind IS NULL OR target_name IS NULL;
ALTER TABLE public.kairos_requests ALTER COLUMN code DROP NOT NULL;
ALTER TABLE public.kairos_requests ALTER COLUMN company_name DROP NOT NULL;
ALTER TABLE public.kairos_requests ALTER COLUMN request_kind SET NOT NULL;
ALTER TABLE public.kairos_requests ALTER COLUMN target_name SET NOT NULL;
ALTER TABLE public.kairos_requests
  DROP CONSTRAINT IF EXISTS kairos_requests_status_check,
  DROP CONSTRAINT IF EXISTS kairos_requests_request_kind_check,
  DROP CONSTRAINT IF EXISTS kairos_requests_target_shape_check;
ALTER TABLE public.kairos_requests
  ADD CONSTRAINT kairos_requests_status_check CHECK (
    status IN ('pending', 'working', 'awaiting_input', 'rejected', 'failed', 'sending', 'sent', 'uncertain')
  ),
  ADD CONSTRAINT kairos_requests_request_kind_check CHECK (
    request_kind IN ('company', 'industry')
  ),
  ADD CONSTRAINT kairos_requests_target_shape_check CHECK (
    (request_kind = 'company' AND code IS NOT NULL AND company_name IS NOT NULL)
    OR (request_kind = 'industry' AND code IS NULL AND industry IS NOT NULL)
  );
CREATE INDEX IF NOT EXISTS kairos_requests_status_created_idx
  ON public.kairos_requests (status, created_at);
CREATE INDEX IF NOT EXISTS kairos_requests_kind_target_idx
  ON public.kairos_requests (request_kind, target_name, created_at DESC);
ALTER TABLE public.kairos_requests ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.kairos_requests FROM anon, authenticated;
