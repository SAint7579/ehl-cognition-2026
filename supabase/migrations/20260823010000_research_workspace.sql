create table if not exists public.investigations (
  id text primary key,
  owner_id uuid references auth.users(id) on delete cascade,
  title text not null,
  objective text not null,
  playbook text not null default 'protein-engineering-v1',
  status text not null check (status in ('queued', 'running', 'complete', 'failed')),
  active_agent text,
  active_stage text,
  error text,
  include_structure boolean not null default true,
  capabilities jsonb not null default '[]'::jsonb,
  devin_session_id text,
  session_url text,
  seen_devin_ids jsonb not null default '[]'::jsonb,
  limitations jsonb not null default '[]'::jsonb,
  created_at timestamptz not null,
  updated_at timestamptz not null
);

create index if not exists investigations_owner_updated_idx
  on public.investigations (owner_id, updated_at desc);

create table if not exists public.investigation_messages (
  id text primary key,
  investigation_id text not null references public.investigations(id) on delete cascade,
  speaker text not null,
  body text not null,
  stage text,
  source_id text,
  artifact_ids jsonb not null default '[]'::jsonb,
  created_at timestamptz not null
);

create index if not exists investigation_messages_job_created_idx
  on public.investigation_messages (investigation_id, created_at);

create table if not exists public.investigation_events (
  investigation_id text not null references public.investigations(id) on delete cascade,
  event_id bigint not null,
  event_type text not null,
  stage text,
  message text not null,
  artifact_id text,
  created_at timestamptz not null,
  primary key (investigation_id, event_id)
);

create index if not exists investigation_events_job_created_idx
  on public.investigation_events (investigation_id, created_at);

create table if not exists public.investigation_artifacts (
  investigation_id text not null references public.investigations(id) on delete cascade,
  owner_id uuid references auth.users(id) on delete cascade,
  artifact_id text not null,
  filename text not null,
  media_type text not null,
  bytes bigint not null check (bytes >= 0),
  stage text not null,
  title text not null,
  purpose text not null,
  storage_path text,
  structured_payload jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (investigation_id, filename)
);

create index if not exists investigation_artifacts_owner_idx
  on public.investigation_artifacts (owner_id, investigation_id);

create table if not exists public.research_results (
  investigation_id text primary key references public.investigations(id) on delete cascade,
  owner_id uuid references auth.users(id) on delete cascade,
  plan_filename text,
  plan_result jsonb,
  synthesis_filename text,
  synthesis_result jsonb,
  simulation_filename text,
  simulation_result jsonb,
  validation_errors jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

create index if not exists research_results_owner_idx
  on public.research_results (owner_id, investigation_id);

create or replace function public.initialize_research_result()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.research_results (investigation_id, owner_id)
  values (new.id, new.owner_id)
  on conflict (investigation_id) do nothing;
  return new;
end;
$$;

drop trigger if exists initialize_research_result_after_investigation on public.investigations;
create trigger initialize_research_result_after_investigation
after insert on public.investigations
for each row execute function public.initialize_research_result();

insert into public.research_results (investigation_id, owner_id)
select id, owner_id from public.investigations
on conflict (investigation_id) do nothing;

insert into storage.buckets (id, name, public, file_size_limit)
values ('research-artifacts', 'research-artifacts', false, 52428800)
on conflict (id) do update
set public = excluded.public,
    file_size_limit = excluded.file_size_limit;

alter table public.investigations enable row level security;
alter table public.investigation_messages enable row level security;
alter table public.investigation_events enable row level security;
alter table public.investigation_artifacts enable row level security;
alter table public.research_results enable row level security;

drop policy if exists "Users manage their investigations" on public.investigations;
create policy "Users manage their investigations"
  on public.investigations
  for all
  to authenticated
  using (owner_id = auth.uid())
  with check (owner_id = auth.uid());

drop policy if exists "Users manage their investigation messages" on public.investigation_messages;
create policy "Users manage their investigation messages"
  on public.investigation_messages
  for all
  to authenticated
  using (
    exists (
      select 1
      from public.investigations
      where investigations.id = investigation_messages.investigation_id
        and investigations.owner_id = auth.uid()
    )
  )
  with check (
    exists (
      select 1
      from public.investigations
      where investigations.id = investigation_messages.investigation_id
        and investigations.owner_id = auth.uid()
    )
  );

drop policy if exists "Users manage their investigation events" on public.investigation_events;
create policy "Users manage their investigation events"
  on public.investigation_events
  for all
  to authenticated
  using (
    exists (
      select 1
      from public.investigations
      where investigations.id = investigation_events.investigation_id
        and investigations.owner_id = auth.uid()
    )
  )
  with check (
    exists (
      select 1
      from public.investigations
      where investigations.id = investigation_events.investigation_id
        and investigations.owner_id = auth.uid()
    )
  );

drop policy if exists "Users manage their investigation artifacts" on public.investigation_artifacts;
create policy "Users manage their investigation artifacts"
  on public.investigation_artifacts
  for all
  to authenticated
  using (owner_id = auth.uid())
  with check (owner_id = auth.uid());

drop policy if exists "Users manage their research results" on public.research_results;
create policy "Users manage their research results"
  on public.research_results
  for all
  to authenticated
  using (owner_id = auth.uid())
  with check (owner_id = auth.uid());

drop policy if exists "Users read their research artifacts" on storage.objects;
create policy "Users read their research artifacts"
  on storage.objects
  for select
  to authenticated
  using (
    bucket_id = 'research-artifacts'
    and (storage.foldername(name))[1] = auth.uid()::text
  );

drop policy if exists "Users write their research artifacts" on storage.objects;
create policy "Users write their research artifacts"
  on storage.objects
  for insert
  to authenticated
  with check (
    bucket_id = 'research-artifacts'
    and (storage.foldername(name))[1] = auth.uid()::text
  );

drop policy if exists "Users update their research artifacts" on storage.objects;
create policy "Users update their research artifacts"
  on storage.objects
  for update
  to authenticated
  using (
    bucket_id = 'research-artifacts'
    and (storage.foldername(name))[1] = auth.uid()::text
  )
  with check (
    bucket_id = 'research-artifacts'
    and (storage.foldername(name))[1] = auth.uid()::text
  );

drop policy if exists "Users delete their research artifacts" on storage.objects;
create policy "Users delete their research artifacts"
  on storage.objects
  for delete
  to authenticated
  using (
    bucket_id = 'research-artifacts'
    and (storage.foldername(name))[1] = auth.uid()::text
  );
