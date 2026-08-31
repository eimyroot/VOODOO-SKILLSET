-- VOODOO-SKILLSET R4 production performance hardening.
-- Cover the voodoo_jobs(plan_id) foreign key so plan deletes/joins and referential
-- checks do not require a full jobs-table scan as fleet history grows.

create index if not exists voodoo_jobs_plan_id_idx
  on public.voodoo_jobs(plan_id);
