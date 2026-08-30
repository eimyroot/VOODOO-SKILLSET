# Deployment

## Vercel web/API deployment

VOODOO-SKILLSET v0.3 ships a Vercel-compatible entrypoint in `api/index.py` and `vercel.json`.

Routes:

- `/` → Control Room
- `/api/health`
- `/api/capabilities`
- `/api/runtime`
- `/api/runs`
- `/api/metrics`
- `/api/learning`
- `/api/evidence`
- `/api/verifier`
- `/api/policies`
- `POST /api/plan`

The Vercel state store is deliberately marked **EPHEMERAL** because no persistent database has been authorized/configured yet. This must not be represented as durable evidence storage.

## Production authority

Deployment is a `DEPLOY` authority class. Repository identity or a generic instruction to "finish" does not manufacture production authority. A dedicated bounded deployment approval remains required before production promotion.

## Isolated execution

The Linux namespace sandbox is for trusted control-plane compute on a compatible Linux host. It uses kernel namespaces + chroot and is not expected to run inside every serverless runtime. Vercel serves the control plane; isolated workers should be deployed as a dedicated worker service or sandbox backend.
