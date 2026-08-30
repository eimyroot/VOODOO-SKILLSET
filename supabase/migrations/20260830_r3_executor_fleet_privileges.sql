-- Explicit server-side privileges for the R3 fleet contract.
-- Do not depend on hosted default privileges.

grant usage on schema public to service_role;
grant select, insert, update, delete on table public.voodoo_plans to service_role;
grant select, insert, update, delete on table public.voodoo_jobs to service_role;
grant select, insert, update, delete on table public.voodoo_fleet_events to service_role;
grant usage, select on sequence public.voodoo_fleet_events_seq_seq to service_role;

revoke all on table public.voodoo_plans from anon, authenticated;
revoke all on table public.voodoo_jobs from anon, authenticated;
revoke all on table public.voodoo_fleet_events from anon, authenticated;
revoke all on sequence public.voodoo_fleet_events_seq_seq from anon, authenticated;
