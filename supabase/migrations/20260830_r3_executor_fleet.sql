-- VOODOO-SKILLSET R3 durable Executor Fleet for Supabase/Postgres.
-- Server-side service_role only. anon/authenticated receive no direct table/RPC access.

create extension if not exists pgcrypto;

do $$
begin
  if not exists (select 1 from pg_type where typname = 'voodoo_job_state') then
    create type voodoo_job_state as enum ('QUEUED','LEASED','EXECUTED','VERIFYING','VERIFIED','FAILED','BLOCKED');
  end if;
end
$$;

create table if not exists public.voodoo_plans (
  plan_id text primary key,
  status text not null check (status in ('VERIFIED_PLAN','BLOCKED')),
  plan_json jsonb not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.voodoo_jobs (
  job_id text primary key,
  plan_id text not null references public.voodoo_plans(plan_id),
  workspace_id text not null,
  capability_id text not null,
  argv jsonb not null check (jsonb_typeof(argv) = 'array' and jsonb_array_length(argv) between 1 and 64),
  cwd text not null default '.',
  verification_spec jsonb not null check (jsonb_typeof(verification_spec) = 'object'),
  workspace_before_sha256 text,
  state voodoo_job_state not null default 'QUEUED',
  priority integer not null default 100,
  available_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  attempts integer not null default 0 check (attempts >= 0),
  max_attempts integer not null default 3 check (max_attempts between 1 and 10),
  execution_worker_id text,
  execution_lease_hash text,
  execution_lease_expires_at timestamptz,
  receipt jsonb,
  receipt_sha256 text,
  verifier_id text,
  verification_lease_hash text,
  verification_lease_expires_at timestamptz,
  verification jsonb,
  last_error text,
  check (workspace_id ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'),
  check (capability_id ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'),
  check (cwd <> '' and length(cwd) <= 512 and cwd !~ '(^/|(^|/)\.\.(/|$))')
);

create index if not exists voodoo_jobs_exec_claim_idx
  on public.voodoo_jobs(state, available_at, priority, created_at);
create index if not exists voodoo_jobs_verify_claim_idx
  on public.voodoo_jobs(state, updated_at);

create table if not exists public.voodoo_fleet_events (
  seq bigint generated always as identity primary key,
  job_id text,
  kind text not null,
  actor text not null,
  payload jsonb not null,
  created_at timestamptz not null default now(),
  prev_hash text not null,
  event_hash text not null unique
);

alter table public.voodoo_plans enable row level security;
alter table public.voodoo_jobs enable row level security;
alter table public.voodoo_fleet_events enable row level security;

revoke all on public.voodoo_plans from anon, authenticated;
revoke all on public.voodoo_jobs from anon, authenticated;
revoke all on public.voodoo_fleet_events from anon, authenticated;

create or replace function public.voodoo_job_json(p_job public.voodoo_jobs)
returns jsonb
language sql
stable
as $$
  select to_jsonb(p_job) - 'execution_lease_hash' - 'verification_lease_hash';
$$;

create or replace function public.voodoo_append_event(
  p_job_id text,
  p_kind text,
  p_actor text,
  p_payload jsonb,
  p_created_at timestamptz default now()
)
returns text
language plpgsql
as $$
declare
  v_prev text;
  v_hash text;
begin
  perform pg_advisory_xact_lock(hashtext('voodoo-fleet-event-chain'));
  select event_hash into v_prev from public.voodoo_fleet_events order by seq desc limit 1;
  v_prev := coalesce(v_prev, repeat('0', 64));
  v_hash := encode(
    digest(
      convert_to(
        v_prev || '|' || coalesce(p_job_id,'') || '|' || p_kind || '|' || p_actor || '|' ||
        p_payload::text || '|' || (extract(epoch from p_created_at)::bigint)::text,
        'UTF8'
      ),
      'sha256'
    ),
    'hex'
  );
  insert into public.voodoo_fleet_events(job_id,kind,actor,payload,created_at,prev_hash,event_hash)
  values(p_job_id,p_kind,p_actor,p_payload,p_created_at,v_prev,v_hash);
  return v_hash;
end;
$$;

create or replace function public.voodoo_record_plan(p_plan jsonb)
returns jsonb
language plpgsql
as $$
declare
  v_plan_id text := p_plan->>'plan_id';
  v_status text := p_plan->>'status';
begin
  if v_plan_id is null or v_plan_id = '' or v_status not in ('VERIFIED_PLAN','BLOCKED') then
    raise exception 'invalid durable plan';
  end if;
  insert into public.voodoo_plans(plan_id,status,plan_json)
  values(v_plan_id,v_status,p_plan)
  on conflict(plan_id) do update set status=excluded.status, plan_json=excluded.plan_json, updated_at=now();
  perform public.voodoo_append_event(null,'PLAN_RECORDED','control-plane',jsonb_build_object('plan_id',v_plan_id,'status',v_status));
  return jsonb_build_object('plan_id',v_plan_id,'status',v_status);
end;
$$;

create or replace function public.voodoo_verified_plan_exists(p_plan_id text)
returns boolean
language sql
stable
as $$
  select exists(select 1 from public.voodoo_plans where plan_id=p_plan_id and status='VERIFIED_PLAN');
$$;

create or replace function public.voodoo_enqueue_job(
  p_plan_id text,
  p_workspace_id text,
  p_capability_id text,
  p_argv jsonb,
  p_cwd text,
  p_verification_spec jsonb,
  p_workspace_before_sha256 text default null,
  p_priority integer default 100,
  p_max_attempts integer default 3,
  p_job_id text default null
)
returns jsonb
language plpgsql
as $$
declare
  v_job_id text := coalesce(p_job_id, 'JOB-' || replace(gen_random_uuid()::text,'-',''));
  v_job public.voodoo_jobs;
begin
  if not public.voodoo_verified_plan_exists(p_plan_id) then
    raise exception 'job enqueue requires durable VERIFIED_PLAN';
  end if;
  if p_verification_spec is null or jsonb_typeof(p_verification_spec) <> 'object' or p_verification_spec = '{}'::jsonb then
    raise exception 'non-empty verification_spec required';
  end if;
  insert into public.voodoo_jobs(
    job_id,plan_id,workspace_id,capability_id,argv,cwd,verification_spec,
    workspace_before_sha256,priority,max_attempts
  ) values(
    v_job_id,p_plan_id,p_workspace_id,p_capability_id,p_argv,p_cwd,p_verification_spec,
    p_workspace_before_sha256,p_priority,p_max_attempts
  ) returning * into v_job;
  perform public.voodoo_append_event(v_job_id,'JOB_ENQUEUED','control-plane',jsonb_build_object(
    'plan_id',p_plan_id,'workspace_id',p_workspace_id,'capability_id',p_capability_id,
    'priority',p_priority,'max_attempts',p_max_attempts
  ));
  return public.voodoo_job_json(v_job);
end;
$$;

create or replace function public.voodoo_reap_expired_leases()
returns integer
language plpgsql
as $$
declare
  r record;
  v_count integer := 0;
  v_next voodoo_job_state;
begin
  for r in
    select * from public.voodoo_jobs
    where (state='LEASED' and execution_lease_expires_at < now())
       or (state='VERIFYING' and verification_lease_expires_at < now())
    for update
  loop
    if r.state='LEASED' then
      v_next := case when r.attempts < r.max_attempts then 'QUEUED'::voodoo_job_state else 'FAILED'::voodoo_job_state end;
      update public.voodoo_jobs set
        state=v_next, execution_worker_id=null, execution_lease_hash=null,
        execution_lease_expires_at=null, updated_at=now(), last_error='execution lease expired'
      where job_id=r.job_id;
      perform public.voodoo_append_event(r.job_id,'EXECUTION_LEASE_EXPIRED','fleet-coordinator',jsonb_build_object(
        'previous_owner',r.execution_worker_id,'next_state',v_next::text
      ));
    else
      update public.voodoo_jobs set
        state='EXECUTED', verifier_id=null, verification_lease_hash=null,
        verification_lease_expires_at=null, updated_at=now(), last_error='verification lease expired'
      where job_id=r.job_id;
      perform public.voodoo_append_event(r.job_id,'VERIFICATION_LEASE_EXPIRED','fleet-coordinator',jsonb_build_object(
        'previous_verifier',r.verifier_id,'next_state','EXECUTED'
      ));
    end if;
    v_count := v_count + 1;
  end loop;
  return v_count;
end;
$$;

create or replace function public.voodoo_claim_execution(p_worker_id text, p_lease_seconds integer default 30)
returns jsonb
language plpgsql
as $$
declare
  v_job public.voodoo_jobs;
  v_token text;
  v_expires timestamptz;
begin
  if p_worker_id !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$' then raise exception 'invalid worker id'; end if;
  if p_lease_seconds < 5 or p_lease_seconds > 300 then raise exception 'invalid lease duration'; end if;
  perform public.voodoo_reap_expired_leases();
  select * into v_job from public.voodoo_jobs
    where state='QUEUED' and available_at<=now() and attempts<max_attempts
    order by priority asc, created_at asc, job_id asc
    for update skip locked limit 1;
  if not found then return null; end if;
  v_token := encode(gen_random_bytes(32),'hex');
  v_expires := now() + make_interval(secs => p_lease_seconds);
  update public.voodoo_jobs set
    state='LEASED', execution_worker_id=p_worker_id,
    execution_lease_hash=encode(digest(convert_to(v_token,'UTF8'),'sha256'),'hex'),
    execution_lease_expires_at=v_expires, attempts=attempts+1, updated_at=now(), last_error=null
  where job_id=v_job.job_id returning * into v_job;
  perform public.voodoo_append_event(v_job.job_id,'EXECUTION_LEASE_GRANTED',p_worker_id,jsonb_build_object(
    'expires_at',v_expires,'attempt',v_job.attempts
  ));
  return public.voodoo_job_json(v_job) || jsonb_build_object('lease_token',v_token,'lease_expires_at',v_expires);
end;
$$;

create or replace function public.voodoo_heartbeat_execution(
  p_job_id text,p_worker_id text,p_token text,p_lease_seconds integer default 30
)
returns timestamptz
language plpgsql
as $$
declare
  v_expires timestamptz;
  v_job public.voodoo_jobs;
begin
  select * into v_job from public.voodoo_jobs where job_id=p_job_id for update;
  if not found or v_job.state<>'LEASED' or v_job.execution_worker_id<>p_worker_id then raise exception 'execution lease ownership mismatch'; end if;
  if v_job.execution_lease_expires_at < now() or v_job.execution_lease_hash <> encode(digest(convert_to(p_token,'UTF8'),'sha256'),'hex') then
    raise exception 'execution lease expired or token invalid';
  end if;
  v_expires := now() + make_interval(secs => p_lease_seconds);
  update public.voodoo_jobs set execution_lease_expires_at=v_expires,updated_at=now() where job_id=p_job_id;
  perform public.voodoo_append_event(p_job_id,'EXECUTION_HEARTBEAT',p_worker_id,jsonb_build_object('expires_at',v_expires));
  return v_expires;
end;
$$;

create or replace function public.voodoo_complete_execution(
  p_job_id text,p_worker_id text,p_token text,p_receipt jsonb,p_receipt_signature_verified boolean
)
returns jsonb
language plpgsql
as $$
declare
  v_job public.voodoo_jobs;
  v_hash text;
begin
  if not p_receipt_signature_verified then raise exception 'unverified execution receipt'; end if;
  if p_receipt->>'verification_status' <> 'UNKNOWN' then raise exception 'execution receipt must remain UNKNOWN'; end if;
  if p_receipt#>>'{result,status}' <> 'EXECUTED' or coalesce((p_receipt#>>'{result,exit_code}')::integer,-1) <> 0 then
    raise exception 'successful execution receipt required';
  end if;
  select * into v_job from public.voodoo_jobs where job_id=p_job_id for update;
  if not found or v_job.state<>'LEASED' or v_job.execution_worker_id<>p_worker_id then raise exception 'execution lease ownership mismatch'; end if;
  if v_job.execution_lease_expires_at < now() or v_job.execution_lease_hash <> encode(digest(convert_to(p_token,'UTF8'),'sha256'),'hex') then
    raise exception 'execution lease expired or token invalid';
  end if;
  v_hash := encode(digest(convert_to(p_receipt::text,'UTF8'),'sha256'),'hex');
  update public.voodoo_jobs set
    state='EXECUTED',receipt=p_receipt,receipt_sha256=v_hash,
    execution_lease_hash=null,execution_lease_expires_at=null,updated_at=now()
  where job_id=p_job_id returning * into v_job;
  perform public.voodoo_append_event(p_job_id,'EXECUTION_RECEIPT_ACCEPTED',p_worker_id,jsonb_build_object(
    'receipt_sha256',v_hash,'verification_status','UNKNOWN','executor_id',p_receipt->>'executor_id'
  ));
  return public.voodoo_job_json(v_job);
end;
$$;

create or replace function public.voodoo_fail_execution(
  p_job_id text,p_worker_id text,p_token text,p_error text,p_retry_delay_seconds integer default 1
)
returns jsonb
language plpgsql
as $$
declare
  v_job public.voodoo_jobs;
  v_next voodoo_job_state;
begin
  select * into v_job from public.voodoo_jobs where job_id=p_job_id for update;
  if not found or v_job.state<>'LEASED' or v_job.execution_worker_id<>p_worker_id then raise exception 'execution lease ownership mismatch'; end if;
  if v_job.execution_lease_hash <> encode(digest(convert_to(p_token,'UTF8'),'sha256'),'hex') then raise exception 'execution lease token invalid'; end if;
  v_next := case when v_job.attempts < v_job.max_attempts then 'QUEUED'::voodoo_job_state else 'FAILED'::voodoo_job_state end;
  update public.voodoo_jobs set
    state=v_next,available_at=now()+make_interval(secs=>greatest(0,p_retry_delay_seconds)),
    execution_worker_id=null,execution_lease_hash=null,execution_lease_expires_at=null,
    updated_at=now(),last_error=left(p_error,2048)
  where job_id=p_job_id returning * into v_job;
  perform public.voodoo_append_event(p_job_id,'EXECUTION_FAILED',p_worker_id,jsonb_build_object(
    'next_state',v_next::text,'attempt',v_job.attempts,'error',left(p_error,512)
  ));
  return public.voodoo_job_json(v_job);
end;
$$;

create or replace function public.voodoo_claim_verification(p_verifier_id text,p_lease_seconds integer default 30)
returns jsonb
language plpgsql
as $$
declare
  v_job public.voodoo_jobs;
  v_token text;
  v_expires timestamptz;
begin
  if p_verifier_id !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$' then raise exception 'invalid verifier id'; end if;
  perform public.voodoo_reap_expired_leases();
  select * into v_job from public.voodoo_jobs
    where state='EXECUTED' and (execution_worker_id is null or execution_worker_id<>p_verifier_id)
    order by updated_at asc,job_id asc
    for update skip locked limit 1;
  if not found then return null; end if;
  v_token := encode(gen_random_bytes(32),'hex');
  v_expires := now()+make_interval(secs=>p_lease_seconds);
  update public.voodoo_jobs set
    state='VERIFYING',verifier_id=p_verifier_id,
    verification_lease_hash=encode(digest(convert_to(v_token,'UTF8'),'sha256'),'hex'),
    verification_lease_expires_at=v_expires,updated_at=now()
  where job_id=v_job.job_id returning * into v_job;
  perform public.voodoo_append_event(v_job.job_id,'VERIFICATION_LEASE_GRANTED',p_verifier_id,jsonb_build_object('expires_at',v_expires));
  return public.voodoo_job_json(v_job) || jsonb_build_object('lease_token',v_token,'lease_expires_at',v_expires);
end;
$$;

create or replace function public.voodoo_complete_verification(
  p_job_id text,p_verifier_id text,p_token text,p_verdict text,p_proof jsonb
)
returns jsonb
language plpgsql
as $$
declare
  v_job public.voodoo_jobs;
  v_verification jsonb;
  v_state voodoo_job_state;
begin
  if p_verdict not in ('VERIFIED','FAILED','BLOCKED') then raise exception 'invalid verification verdict'; end if;
  select * into v_job from public.voodoo_jobs where job_id=p_job_id for update;
  if not found or v_job.state<>'VERIFYING' or v_job.verifier_id<>p_verifier_id then raise exception 'verification lease ownership mismatch'; end if;
  if v_job.execution_worker_id=p_verifier_id then raise exception 'executor cannot verify its own job'; end if;
  if v_job.verification_lease_expires_at < now() or v_job.verification_lease_hash <> encode(digest(convert_to(p_token,'UTF8'),'sha256'),'hex') then
    raise exception 'verification lease expired or token invalid';
  end if;
  if p_verdict='VERIFIED' and (
    p_proof->'checks' is null or jsonb_typeof(p_proof->'checks')<>'object' or p_proof->'checks'='{}'::jsonb or
    exists(select 1 from jsonb_each(p_proof->'checks') where value <> 'true'::jsonb)
  ) then raise exception 'VERIFIED requires non-empty independently passing checks'; end if;
  v_state := p_verdict::voodoo_job_state;
  v_verification := jsonb_build_object(
    'verdict',p_verdict,'verifier_id',p_verifier_id,'proof',p_proof,
    'receipt_sha256',v_job.receipt_sha256,'verified_at',now()
  );
  update public.voodoo_jobs set
    state=v_state,verification=v_verification,verification_lease_hash=null,
    verification_lease_expires_at=null,updated_at=now(),
    last_error=case when p_verdict='VERIFIED' then null else 'independent verification '||lower(p_verdict) end
  where job_id=p_job_id returning * into v_job;
  perform public.voodoo_append_event(p_job_id,'INDEPENDENT_VERIFICATION',p_verifier_id,v_verification);
  return public.voodoo_job_json(v_job);
end;
$$;

create or replace function public.voodoo_fleet_stats()
returns jsonb
language sql
stable
as $$
  select jsonb_build_object(
    'backend','supabase-postgres',
    'counts',jsonb_build_object(
      'QUEUED',count(*) filter(where state='QUEUED'),
      'LEASED',count(*) filter(where state='LEASED'),
      'EXECUTED',count(*) filter(where state='EXECUTED'),
      'VERIFYING',count(*) filter(where state='VERIFYING'),
      'VERIFIED',count(*) filter(where state='VERIFIED'),
      'FAILED',count(*) filter(where state='FAILED'),
      'BLOCKED',count(*) filter(where state='BLOCKED')
    ),
    'event_count',(select count(*) from public.voodoo_fleet_events),
    'event_head',(select event_hash from public.voodoo_fleet_events order by seq desc limit 1),
    'receipt_is_verification',false
  ) from public.voodoo_jobs;
$$;

create or replace function public.voodoo_verify_event_chain()
returns jsonb
language plpgsql
stable
as $$
declare
  r record;
  v_prev text := repeat('0',64);
  v_expected text;
  v_count bigint := 0;
begin
  for r in select * from public.voodoo_fleet_events order by seq asc loop
    if r.prev_hash <> v_prev then
      return jsonb_build_object('ok',false,'reason','prev_hash mismatch','seq',r.seq);
    end if;
    v_expected := encode(digest(convert_to(
      v_prev || '|' || coalesce(r.job_id,'') || '|' || r.kind || '|' || r.actor || '|' ||
      r.payload::text || '|' || (extract(epoch from r.created_at)::bigint)::text,
      'UTF8'),'sha256'),'hex');
    if r.event_hash <> v_expected then
      return jsonb_build_object('ok',false,'reason','event_hash mismatch','seq',r.seq);
    end if;
    v_prev := r.event_hash;
    v_count := v_count + 1;
  end loop;
  return jsonb_build_object('ok',true,'reason',v_count::text||' events verified','event_count',v_count,'head',case when v_count=0 then null else v_prev end);
end;
$$;

revoke all on function public.voodoo_job_json(public.voodoo_jobs) from public, anon, authenticated;
revoke all on function public.voodoo_append_event(text,text,text,jsonb,timestamptz) from public, anon, authenticated;
revoke all on function public.voodoo_record_plan(jsonb) from public, anon, authenticated;
revoke all on function public.voodoo_verified_plan_exists(text) from public, anon, authenticated;
revoke all on function public.voodoo_enqueue_job(text,text,text,jsonb,text,jsonb,text,integer,integer,text) from public, anon, authenticated;
revoke all on function public.voodoo_reap_expired_leases() from public, anon, authenticated;
revoke all on function public.voodoo_claim_execution(text,integer) from public, anon, authenticated;
revoke all on function public.voodoo_heartbeat_execution(text,text,text,integer) from public, anon, authenticated;
revoke all on function public.voodoo_complete_execution(text,text,text,jsonb,boolean) from public, anon, authenticated;
revoke all on function public.voodoo_fail_execution(text,text,text,text,integer) from public, anon, authenticated;
revoke all on function public.voodoo_claim_verification(text,integer) from public, anon, authenticated;
revoke all on function public.voodoo_complete_verification(text,text,text,text,jsonb) from public, anon, authenticated;
revoke all on function public.voodoo_fleet_stats() from public, anon, authenticated;
revoke all on function public.voodoo_verify_event_chain() from public, anon, authenticated;

grant execute on function public.voodoo_job_json(public.voodoo_jobs) to service_role;
grant execute on function public.voodoo_append_event(text,text,text,jsonb,timestamptz) to service_role;
grant execute on function public.voodoo_record_plan(jsonb) to service_role;
grant execute on function public.voodoo_verified_plan_exists(text) to service_role;
grant execute on function public.voodoo_enqueue_job(text,text,text,jsonb,text,jsonb,text,integer,integer,text) to service_role;
grant execute on function public.voodoo_reap_expired_leases() to service_role;
grant execute on function public.voodoo_claim_execution(text,integer) to service_role;
grant execute on function public.voodoo_heartbeat_execution(text,text,text,integer) to service_role;
grant execute on function public.voodoo_complete_execution(text,text,text,jsonb,boolean) to service_role;
grant execute on function public.voodoo_fail_execution(text,text,text,text,integer) to service_role;
grant execute on function public.voodoo_claim_verification(text,integer) to service_role;
grant execute on function public.voodoo_complete_verification(text,text,text,text,jsonb) to service_role;
grant execute on function public.voodoo_fleet_stats() to service_role;
grant execute on function public.voodoo_verify_event_chain() to service_role;
