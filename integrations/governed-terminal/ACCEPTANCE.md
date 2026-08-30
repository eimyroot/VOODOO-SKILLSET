# Governed Terminal acceptance gate

- unknown executable => BLOCKED
- shell wrapper => BLOCKED
- shell chaining/redirection => BLOCKED
- git status => READ_ONLY
- git commit => REPO_WRITE
- git push => REMOTE_WRITE
- compute without isolated runner/grant => BLOCKED
- grants are target/class/command-prefix bound
- expired grant => BLOCKED
- execution uses shell=False
- receipt stores exit code and output digests
- receipt status is not automatically VERIFIED
- production mutation remains BLOCKED
