# Architecture

```text
USER GOAL
  -> Intent Compiler
  -> Capability Router
  -> Dynamic DAG Composer
  -> Governed Runtime
       -> Skills / Agents / Subagents
       -> Plugins / Tools
       -> CASTER-MINAL governed terminal boundary
  -> Shared Blackboard
  -> Independent Verifier
  -> Evidence Ledger
  -> Learning Signal
```

## Authority separation
- CASER: workspace + orchestration context.
- CASER-SOURCER: truth/provenance.
- CASER-MINER: research intelligence only.
- CASTER-MINAL / governed-terminal: execution boundary only.
- Independent Verifier: outcome verification.
- Evidence receipts never self-promote to VERIFIED.

## Core invariant
`PROJECT IDENTITY != EXECUTION AUTHORITY`

## CASER workspace
`SCRATCH -> WORKSPACE -> VAULT` is implemented as an explicit bounded zone manager. VAULT overwrites are denied by default. Workspace identity still does not grant repository authority.

## Execution envelope
The runtime defines a deny-by-default `NetworkPolicy` and `ExecutionEnvelope`. In v0.2 these are enforceable control-plane contracts; CPU/memory isolation is intentionally labelled `UNENFORCED_LOCAL_REFERENCE` until a real microVM/container adapter is deployed.
