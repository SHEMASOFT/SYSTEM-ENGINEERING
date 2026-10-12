# Policy: Security

1. Never access production systems from development or agent workflows unless explicitly
   authorized.
2. Apply least privilege to credentials, roles and access.
3. Dependencies must be reviewed for known vulnerabilities and license compatibility
   before release.
4. Critical security findings block G5 until resolved or explicitly accepted by the owner.
5. Security-relevant decisions are recorded as ADRs with `category: security`.
6. Inputs are validated; secrets are never logged.
7. Offensive testing (e.g. `pentester`) requires a defined, authorized scope.
