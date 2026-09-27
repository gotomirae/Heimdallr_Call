-- PRD Ref: §8.7 · Drive 산업 폴더명 불일치 Telegram 확인
-- Existing installations: apply once in the Heimdallr Supabase SQL Editor.
ALTER TABLE public.kairos_requests
  ADD COLUMN IF NOT EXISTS drive_folder_name TEXT,
  ADD COLUMN IF NOT EXISTS drive_folder_url TEXT,
  ADD COLUMN IF NOT EXISTS drive_folder_confirmed BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS confirmation_message_id BIGINT,
  ADD COLUMN IF NOT EXISTS confirmation_response TEXT,
  ADD COLUMN IF NOT EXISTS confirmation_responded_at TIMESTAMPTZ;

ALTER TABLE public.kairos_requests
  DROP CONSTRAINT IF EXISTS kairos_requests_status_check;
ALTER TABLE public.kairos_requests
  ADD CONSTRAINT kairos_requests_status_check CHECK (
    status IN (
      'pending', 'working', 'awaiting_input', 'rejected',
      'failed', 'sending', 'sent', 'uncertain'
    )
  );
