-- VOODOO-SKILLSET R4 fleet security hardening.
-- Keep the service-role Control Plane on explicit governed RPCs rather than direct mutation.

-- Pin search_path for every fleet function. This removes role-mutable name resolution,
-- which is especially important for SECURITY DEFINER functions.
alter function public.voodoo_job_json(public.voodoo_jobs) set search_path = pg_catalog, public;
alter function public.voodoo_append_event(text,text,text,jsonb,timestamptz) set search_path = pg_catalog, public;
alter function public.voodoo_record_plan(jsonb) set search_path = pg_catalog, public;
alter function public.voodoo_verified_plan_exists(text) set search_path = pg_catalog, public;
alter function public.voodoo_enqueue_job(text,text,text,jsonb,text,jsonb,text,integer,integer,text) set search_path = pg_catalog, public;
alter function public.voodoo_reap_expired_leases() set search_path = pg_catalog, public;
alter function public.voodoo_claim_execution(text,integer) set search_path = pg_catalog, public;
alter function public.voodoo_heartbeat_execution(text,text,text,integer) set search_path = pg_catalog, public;
alter function public.voodoo_complete_execution(text,text,text,jsonb,boolean) set search_path = pg_catalog, public;
alter function public.voodoo_fail_execution(text,text,text,text,integer) set search_path = pg_catalog, public;
alter function public.voodoo_claim_verification(text,integer) set search_path = pg_catalog, public;
alter function public.voodoo_complete_verification(text,text,text,text,jsonb) set search_path = pg_catalog, public;
alter function public.voodoo_fleet_stats() set search_path = pg_catalog, public;
alter function public.voodoo_verify_event_chain() set search_path = pg_catalog, public;

-- Mutating RPCs run with the migration-owner authority. anon/authenticated still cannot
-- execute them, and the server-side service_role can only enter through the functions
-- explicitly granted in the R3 contract.
alter function public.voodoo_append_event(text,text,text,jsonb,timestamptz) security definer;
alter function public.voodoo_record_plan(jsonb) security definer;
alter function public.voodoo_enqueue_job(text,text,text,jsonb,text,jsonb,text,integer,integer,text) security definer;
alter function public.voodoo_reap_expired_leases() security definer;
alter function public.voodoo_claim_execution(text,integer) security definer;
alter function public.voodoo_heartbeat_execution(text,text,text,integer) security definer;
alter function public.voodoo_complete_execution(text,text,text,jsonb,boolean) security definer;
alter function public.voodoo_fail_execution(text,text,text,text,integer) security definer;
alter function public.voodoo_claim_verification(text,integer) security definer;
alter function public.voodoo_complete_verification(text,text,text,text,jsonb) security definer;

-- Control Plane may inspect durable truth directly, but direct mutation is denied.
revoke insert, update, delete on table public.voodoo_plans from service_role;
revoke insert, update, delete on table public.voodoo_jobs from service_role;
revoke insert, update, delete on table public.voodoo_fleet_events from service_role;
grant select on table public.voodoo_plans to service_role;
grant select on table public.voodoo_jobs to service_role;
grant select on table public.voodoo_fleet_events to service_role;

-- Identity sequence is only consumed by the SECURITY DEFINER append function.
revoke all on sequence public.voodoo_fleet_events_seq_seq from service_role;

-- Internal helpers are not part of the network RPC surface.
revoke execute on function public.voodoo_job_json(public.voodoo_jobs) from service_role;
revoke execute on function public.voodoo_append_event(text,text,text,jsonb,timestamptz) from service_role;
revoke execute on function public.voodoo_reap_expired_leases() from service_role;
