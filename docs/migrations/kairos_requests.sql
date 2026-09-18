-- PRD Ref: §8 · Heimdallr Telegram → Kairos handoff
-- Apply once in the Heimdallr Supabase SQL Editor before deploying the listener.
CREATE TABLE IF NOT EXISTS public.kairos_requests (
  update_id BIGINT PRIMARY KEY,
  chat_id BIGINT NOT NULL,
  user_id BIGINT NOT NULL,
  code TEXT NOT NULL REFERENCES public.krx_universe(code),
  company_name TEXT NOT NULL,
  raw_text TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'working', 'rejected', 'sending', 'sent', 'uncertain')),
  notion_url TEXT,
  industry TEXT,
  telegram_message_id BIGINT,
  error TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  claimed_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS kairos_requests_status_created_idx
  ON public.kairos_requests (status, created_at);
ALTER TABLE public.kairos_requests ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.kairos_requests FROM anon, authenticated;
