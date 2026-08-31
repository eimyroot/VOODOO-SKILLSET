-- VOODOO-SKILLSET R4 hosted Supabase parity hardening.
-- Supabase installs pgcrypto functions in the trusted `extensions` schema, while
-- vanilla PostgreSQL commonly resolves them from `public`. Keep a fixed search_path
-- and include both trusted application/extension schemas so SECURITY DEFINER fleet
-- RPCs behave identically on hosted Supabase and CI PostgreSQL.

alter function public.voodoo_job_json(public.voodoo_jobs) set search_path = pg_catalog, public, extensions;
alter function public.voodoo_append_event(text,text,text,jsonb,timestamptz) set search_path = pg_catalog, public, extensions;
alter function public.voodoo_record_plan(jsonb) set search_path = pg_catalog, public, extensions;
alter function public.voodoo_verified_plan_exists(text) set search_path = pg_catalog, public, extensions;
alter function public.voodoo_enqueue_job(text,text,text,jsonb,text,jsonb,text,integer,integer,text) set search_path = pg_catalog, public, extensions;
alter function public.voodoo_reap_expired_leases() set search_path = pg_catalog, public, extensions;
alter function public.voodoo_claim_execution(text,integer) set search_path = pg_catalog, public, extensions;
alter function public.voodoo_heartbeat_execution(text,text,text,integer) set search_path = pg_catalog, public, extensions;
alter function public.voodoo_complete_execution(text,text,text,jsonb,boolean) set search_path = pg_catalog, public, extensions;
alter function public.voodoo_fail_execution(text,text,text,text,integer) set search_path = pg_catalog, public, extensions;
alter function public.voodoo_claim_verification(text,integer) set search_path = pg_catalog, public, extensions;
alter function public.voodoo_complete_verification(text,text,text,text,jsonb) set search_path = pg_catalog, public, extensions;
alter function public.voodoo_fleet_stats() set search_path = pg_catalog, public, extensions;
alter function public.voodoo_verify_event_chain() set search_path = pg_catalog, public, extensions;
