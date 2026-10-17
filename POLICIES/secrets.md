# Policy: Secrets

1. Never commit secrets: `.env`, credentials, private keys, tokens or passwords.
2. Never generate or store real credentials as part of a workflow.
3. `.gitignore` excludes `.env*`, `*.key`, `*.pem`, `*.p12`, `*.pfx`, `credentials*`,
   `secrets*`, `tokens*`.
4. The `doctor` scans for obvious secret files and fails if any are found.
5. Use environment variables or an external secret manager; reference secrets by name,
   never by value.
6. If a secret is accidentally exposed: stop, report it, rotate the secret, and record the
   incident. Do not attempt to hide it.
