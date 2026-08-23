alter table public.investigations
  add column if not exists playbook_id text,
  add column if not exists playbook_title text;
