# Security model

VOODOO-SKILLSET is fail-closed.

- UNKNOWN != PASS
- MISSING != PASS
- UNVERIFIED != PASS
- READ may be auto-allowed inside target scope.
- COMPUTE requires an isolated runner.
- FILE/REPO/REMOTE WRITE requires bounded authority.
- DEPLOY requires dedicated deploy authority.
- DESTRUCTIVE and PRIVILEGED operations require one-operation approval.
- Shell wrappers, metacharacter chaining and unknown executables are blocked by governed-terminal.
- ExecutionReceipt != independent verification.
