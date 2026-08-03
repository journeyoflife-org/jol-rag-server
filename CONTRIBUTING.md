# Contributing to jol-rag-server

Thank you for contributing to the Journey of Life RAG service. This
repository is the single source of truth for everything RAG-specific:
application code, deployment automation, monitoring, and documentation.

## Ground Rules

1. **No secrets, ever.** No API keys, passwords, tokens, private keys, or
   real personal data in code, tests, fixtures, or docs. CI rejects
   violations. Use `.env.example` placeholders and Vault references.
2. **GDPR first.** Do not log, cache, or store direct personal identifiers.
   Use the pseudonymisation helper (`app.auth.pseudonymise_user_id`).
3. **Pinned dependencies.** All Python dependencies are pinned in
   `src/requirements.txt`; bump versions deliberately and check
   `make scan-deps` before proposing upgrades.
4. **Tests required** for every behaviour change: `make test` must pass.

## Development Setup

```bash
git clone git@github.com:JourneyOfLife/jol-rag-server.git
cd jol-rag-server
make install-dev          # venv + runtime + dev dependencies
make validate             # lint (ruff/yamllint/shellcheck) + tests
```

## Repository Layout

| Path | Purpose |
|---|---|
| `src/` | FastAPI application, workers, Dockerfile, requirements |
| `tests/` | pytest suite (unit + integration with mocked services) |
| `ansible/` | Provisioning & deployment to rag-prod-lt01 |
| `deploy/` | One-time host bootstrap scripts (Docker, LUKS) |
| `scripts/` | Operational scripts (backup, restore, TLS, audit hardening) |
| `monitoring/` | Prometheus scrape config, Grafana dashboard |
| `docs/` | Architecture, runbook, API reference, DPIA, compliance |
| `load/` | Locust load-test scenarios |

## Change Workflow

1. Branch from `main`: `feat/...`, `fix/...`, `docs/...`.
2. Keep changes focused; reference the issue in commit messages.
3. Run `make validate` locally — CI enforces the same gate.
4. Open a PR; require at least one review from CODEOWNERS.
5. Deployment changes (`ansible/`, `docker-compose.yml`, `Dockerfile`)
   need a note in the PR describing the rollback procedure.

## Commit Style

Imperative mood, short subject (`Add per-role rate limiting`), body
explaining *why*. Compliance-relevant changes must cite the control
(e.g., `GDPR Art. 17`, `SOC 2 CC6.1`).

## Code of Conduct

Be respectful. This project serves a mission platform; conduct unbecoming
of a professional environment is not tolerated.
