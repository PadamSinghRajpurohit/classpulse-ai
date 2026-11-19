-- ClassPulse remote storage: group-level session summaries only.
-- This project-specific table deliberately avoids generic names in an existing
-- Supabase project. Never add raw video/audio, face embeddings, student names,
-- or row-level behavioral scores here.

create table if not exists public.classpulse_session_summaries (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null references auth.users (id) on delete cascade,
    class_name text not null check (char_length(class_name) between 1 and 120),
    started_at timestamptz not null default now(),
    ended_at timestamptz,
    enrollment_count integer not null default 0 check (enrollment_count >= 0),
    attendance_count integer not null default 0 check (attendance_count >= 0),
    engagement_score real check (engagement_score between 0 and 100),
    participation_count integer not null default 0 check (participation_count >= 0),
    summary jsonb not null default '{}'::jsonb,
    constraint classpulse_attendance_within_enrollment
        check (attendance_count <= enrollment_count),
    constraint classpulse_summary_aggregate_keys_only
        check (summary - 'trend_points' - 'video_quality' - 'audio_quality' - 'recommendation_codes' = '{}'::jsonb)
);

create index if not exists classpulse_owner_started_idx
    on public.classpulse_session_summaries (owner_id, started_at desc);

alter table public.classpulse_session_summaries enable row level security;
alter table public.classpulse_session_summaries force row level security;
revoke all on table public.classpulse_session_summaries from anon;
grant select, insert, update, delete on public.classpulse_session_summaries to authenticated;

-- Idempotent and non-destructive policy creation.
do $$
begin
    if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'classpulse_session_summaries' and policyname = 'classpulse_read_own') then
        create policy classpulse_read_own on public.classpulse_session_summaries for select to authenticated using (owner_id = (select auth.uid()));
    end if;
    if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'classpulse_session_summaries' and policyname = 'classpulse_insert_own') then
        create policy classpulse_insert_own on public.classpulse_session_summaries for insert to authenticated with check (owner_id = (select auth.uid()));
    end if;
    if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'classpulse_session_summaries' and policyname = 'classpulse_update_own') then
        create policy classpulse_update_own on public.classpulse_session_summaries for update to authenticated using (owner_id = (select auth.uid())) with check (owner_id = (select auth.uid()));
    end if;
    if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'classpulse_session_summaries' and policyname = 'classpulse_delete_own') then
        create policy classpulse_delete_own on public.classpulse_session_summaries for delete to authenticated using (owner_id = (select auth.uid()));
    end if;
end $$;
