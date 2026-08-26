-- Supabase migration for the multi-user foundation.
-- The application must use a user's auth.uid() as user_id; never trust a
-- user_id supplied by an untrusted browser request.

create extension if not exists pgcrypto;

create table if not exists public.user_profiles (
    id uuid primary key references auth.users(id) on delete cascade,
    email text,
    full_name text,
    avatar_url text,
    google_subject text unique,
    cv_path text,
    cv_hash text,
    preferences jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now())
);

alter table public.user_profiles add column if not exists google_subject text;
alter table public.user_profiles add column if not exists cv_hash text;
create unique index if not exists idx_user_profiles_google_subject
    on public.user_profiles(google_subject)
    where google_subject is not null;

create table if not exists public.jobs (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    canonical_url text not null,
    source text not null default '',
    source_job_id text,
    title text not null default '',
    company text not null default '',
    location text,
    description text,
    date_posted text,
    status text not null default 'Nuevo',
    archived boolean not null default false,
    archive_reason text,
    -- NULL until the corresponding stage has produced a hash. This avoids
    -- treating every unanalyzed job as the same cache entry.
    content_hash text,
    analysis_hash text,
    analysis jsonb,
    raw_data jsonb not null default '{}'::jsonb,
    missing_streak integer not null default 0,
    sync_status text not null default 'active',
    invalidated_at timestamptz,
    invalid_reason text,
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now()),
    unique (user_id, canonical_url),
    unique (user_id, source, source_job_id),
    unique (user_id, id)
);

alter table public.jobs add column if not exists source_job_id text;
alter table public.jobs add column if not exists experience_hint integer not null default 0;
alter table public.jobs add column if not exists missing_streak integer not null default 0;
alter table public.jobs add column if not exists sync_status text not null default 'active';
alter table public.jobs add column if not exists invalidated_at timestamptz;
alter table public.jobs add column if not exists invalid_reason text;

create table if not exists public.job_runs (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    run_key text not null,
    status text not null default 'running',
    started_at timestamptz not null default timezone('utc', now()),
    finished_at timestamptz,
    stats jsonb not null default '{}'::jsonb,
    errors jsonb not null default '[]'::jsonb,
    unique (user_id, run_key),
    unique (user_id, id)
);

create table if not exists public.run_jobs (
    user_id uuid not null references auth.users(id) on delete cascade,
    run_id uuid not null,
    job_id uuid not null,
    created_at timestamptz not null default timezone('utc', now()),
    primary key (user_id, run_id, job_id),
    foreign key (user_id, run_id) references public.job_runs(user_id, id) on delete cascade,
    foreign key (user_id, job_id) references public.jobs(user_id, id) on delete cascade
);

create table if not exists public.feedback (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    job_id uuid,
    feedback text not null,
    status text not null default 'pending',
    created_at timestamptz not null default timezone('utc', now()),
    completed_at timestamptz,
    foreign key (user_id, job_id) references public.jobs(user_id, id) on delete cascade
);

create table if not exists public.notion_connections (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    workspace_id text,
    workspace_name text,
    database_id text not null,
    access_token text,
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now()),
    unique (user_id, database_id)
);

-- Scheduler state is separate from profiles so claiming is atomic and retryable.
create table if not exists public.workflow_schedules (
    user_id uuid primary key references auth.users(id) on delete cascade,
    config jsonb not null default '{}'::jsonb,
    next_run_at timestamptz not null default timezone('utc', now()),
    claimed_until timestamptz,
    enabled boolean not null default true,
    updated_at timestamptz not null default timezone('utc', now())
);

create or replace function public.claim_due_workflows(p_limit integer, p_lease_seconds integer)
returns setof public.workflow_schedules
language plpgsql
security definer
set search_path = public
as $$
begin
    return query
    with candidates as (
        select s.user_id
        from public.workflow_schedules s
        where s.enabled and s.next_run_at <= timezone('utc', now())
          and (s.claimed_until is null or s.claimed_until < timezone('utc', now()))
        order by s.next_run_at
        limit greatest(1, least(p_limit, 100))
        for update skip locked
    )
    update public.workflow_schedules s
       set claimed_until = timezone('utc', now()) + make_interval(secs => greatest(60, least(p_lease_seconds, 86400))),
           updated_at = timezone('utc', now())
      from candidates c
     where s.user_id = c.user_id
    returning s.*;
end;
$$;

revoke all on function public.claim_due_workflows(integer, integer) from public;
grant execute on function public.claim_due_workflows(integer, integer) to service_role;

create index if not exists idx_user_profiles_email on public.user_profiles(email);
create index if not exists idx_jobs_user_updated on public.jobs(user_id, updated_at desc);
create index if not exists idx_jobs_user_status on public.jobs(user_id, status);
create index if not exists idx_jobs_user_hashes on public.jobs(user_id, content_hash, analysis_hash);
create index if not exists idx_jobs_user_source_identity on public.jobs(user_id, source, source_job_id);
create index if not exists idx_jobs_user_sync_status on public.jobs(user_id, sync_status, missing_streak);
create index if not exists idx_job_runs_user_started on public.job_runs(user_id, started_at desc);
create index if not exists idx_run_jobs_run on public.run_jobs(user_id, run_id);
create index if not exists idx_run_jobs_job on public.run_jobs(user_id, job_id);
create index if not exists idx_feedback_user_status on public.feedback(user_id, status, created_at desc);
create index if not exists idx_notion_connections_user on public.notion_connections(user_id);
create index if not exists idx_workflow_schedules_due on public.workflow_schedules(next_run_at, claimed_until)
where enabled;

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = timezone('utc', now());
    return new;
end;
$$;

drop trigger if exists set_workflow_schedules_updated_at on public.workflow_schedules;
create trigger set_workflow_schedules_updated_at
before update on public.workflow_schedules
for each row execute function public.set_updated_at();

drop trigger if exists set_user_profiles_updated_at on public.user_profiles;
create trigger set_user_profiles_updated_at
before update on public.user_profiles
for each row execute function public.set_updated_at();

drop trigger if exists set_jobs_updated_at on public.jobs;
create trigger set_jobs_updated_at
before update on public.jobs
for each row execute function public.set_updated_at();

drop trigger if exists set_notion_connections_updated_at on public.notion_connections;
create trigger set_notion_connections_updated_at
before update on public.notion_connections
for each row execute function public.set_updated_at();

alter table public.user_profiles enable row level security;
alter table public.jobs enable row level security;
alter table public.job_runs enable row level security;
alter table public.run_jobs enable row level security;
alter table public.feedback enable row level security;
alter table public.notion_connections enable row level security;
alter table public.workflow_schedules enable row level security;

drop policy if exists user_profiles_owner on public.user_profiles;
create policy user_profiles_owner on public.user_profiles
for all using (id = auth.uid()) with check (id = auth.uid());

drop policy if exists jobs_owner on public.jobs;
create policy jobs_owner on public.jobs
for all using (user_id = auth.uid()) with check (user_id = auth.uid());

drop policy if exists job_runs_owner on public.job_runs;
create policy job_runs_owner on public.job_runs
for all using (user_id = auth.uid()) with check (user_id = auth.uid());

drop policy if exists run_jobs_owner on public.run_jobs;
create policy run_jobs_owner on public.run_jobs
for all using (
    user_id = auth.uid()
    and exists (select 1 from public.job_runs r where r.id = run_id and r.user_id = auth.uid())
    and exists (select 1 from public.jobs j where j.id = job_id and j.user_id = auth.uid())
)
with check (
    user_id = auth.uid()
    and exists (select 1 from public.job_runs r where r.id = run_id and r.user_id = auth.uid())
    and exists (select 1 from public.jobs j where j.id = job_id and j.user_id = auth.uid())
);

drop policy if exists feedback_owner on public.feedback;
create policy feedback_owner on public.feedback
for all using (user_id = auth.uid()) with check (user_id = auth.uid());

drop policy if exists notion_connections_owner on public.notion_connections;
create policy notion_connections_owner on public.notion_connections
for all using (user_id = auth.uid()) with check (user_id = auth.uid());

drop policy if exists workflow_schedules_owner on public.workflow_schedules;
create policy workflow_schedules_owner on public.workflow_schedules
for all using (user_id = auth.uid()) with check (user_id = auth.uid());

-- CVs are private. Objects must be stored below <auth.uid>/ so the policy
-- remains enforceable even when a client knows another object's path.
insert into storage.buckets (id, name, public)
values ('cv-files', 'cv-files', false)
on conflict (id) do update set public = false;

drop policy if exists cv_files_select on storage.objects;
create policy cv_files_select on storage.objects
for select to authenticated
using (bucket_id = 'cv-files' and (storage.foldername(name))[1] = (auth.uid())::text);

drop policy if exists cv_files_insert on storage.objects;
create policy cv_files_insert on storage.objects
for insert to authenticated
with check (bucket_id = 'cv-files' and (storage.foldername(name))[1] = (auth.uid())::text);

drop policy if exists cv_files_update on storage.objects;
create policy cv_files_update on storage.objects
for update to authenticated
using (bucket_id = 'cv-files' and (storage.foldername(name))[1] = (auth.uid())::text)
with check (bucket_id = 'cv-files' and (storage.foldername(name))[1] = (auth.uid())::text);

drop policy if exists cv_files_delete on storage.objects;
create policy cv_files_delete on storage.objects
for delete to authenticated
using (bucket_id = 'cv-files' and (storage.foldername(name))[1] = (auth.uid())::text);
