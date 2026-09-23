# Encrypted secrets root (ADR-003 amendment, R3 convention)

Files committed here MUST be genuine SOPS output (`sops --encrypt --in-place`).
Plaintext in this directory is a security incident: remove from history and
rotate. Decrypt for use: `SOPS_AGE_KEY_FILE=<identity> sops -d <file>` —
never into a tracked path. See jol-infrastructure
`docs/security/sops-rollout-instructions.md` (church) /
`SOPS-PUBLICATION.md` in jol-m-compliance (marketplace).
