---
name: governed-terminal
description: Fail-closed terminal orchestration for CASER projects. Plans, classifies, authorizes, executes and receipts terminal operations without granting AI an unrestricted shell.
version: 0.1.0
status: IMPLEMENTED_SCAFFOLD
owner: V-One / CASER
---

# Governed Terminal Skill

## Core invariant
`PROJECT IDENTITY != EXECUTION AUTHORITY`

Default mode: `READ_ONLY`.

Operation classes: `READ_ONLY | COMPUTE | FILE_WRITE | REPO_WRITE | REMOTE_WRITE | DEPLOY | DESTRUCTIVE | PRIVILEGED | BLOCKED`.

Mandatory properties preserved by VOODOO-SKILLSET:
- classify every command independently;
- fail closed on unknown commands and shell metacharacters;
- compute requires an isolated runner;
- writes require explicit target/class/prefix-bound authorization;
- execute with `shell=false`;
- emit receipts with output digests;
- receipt is not independent verification;
- production mutation remains blocked by default.

Source: user-selected ChatGPT Library folder `/CASER/SkillZ/governed-terminal`, read 2026-08-30.
