# =============================================================================
# JOL RAG Server — Makefile
# Common targets for local development, validation, testing, and deployment.
# =============================================================================

SHELL := /bin/bash
PYTHON ?= python3
VENV ?= .venv
PIP := $(VENV)/bin/pip
PYTEST := $(VENV)/bin/python -m pytest
RUFF := $(VENV)/bin/ruff

.PHONY: help venv install install-dev lint lint-python lint-yaml lint-shell \
        test test-cov scan scan-deps scan-image validate certs deploy clean

## help: Show this help
help:
	@grep -E '^## ' $(MAKEFILE_LIST) | sed 's/## /  /'

## venv: Create the local virtual environment
venv:
	$(PYTHON) -m venv $(VENV)

## install: Install runtime dependencies
install: venv
	$(PIP) install -q --upgrade pip
	$(PIP) install -q -r src/requirements.txt

## install-dev: Install runtime + development dependencies
install-dev: venv
	$(PIP) install -q --upgrade pip
	$(PIP) install -q -r src/requirements.txt -r requirements-dev.txt

## lint: Run all linters (Python, YAML, shell)
lint: lint-python lint-yaml lint-shell

## lint-python: Ruff lint over src/ and tests/
lint-python:
	$(RUFF) check src tests
	$(RUFF) format --check src tests

## lint-yaml: yamllint over YAML assets
lint-yaml:
	$(VENV)/bin/yamllint -c .yamllint.yaml ansible monitoring deploy .github

## lint-shell: shellcheck over shell scripts
lint-shell:
	shellcheck scripts/*.sh deploy/*.sh scripts/tls/*.sh

## test: Run the unit/integration test suite
test:
	PYTHONPATH=src $(PYTEST)

## test-cov: Run tests with coverage report
test-cov:
	PYTHONPATH=src $(PYTEST) --cov=app --cov-report=term-missing

## scan: Dependency + image vulnerability scanning (trivy + pip-audit)
scan: scan-deps scan-image

## scan-deps: Audit Python dependencies for known CVEs
scan-deps:
	$(VENV)/bin/pip-audit -r src/requirements.txt

## scan-image: Build and scan the RAG API container image (requires docker + trivy)
scan-image:
	docker build -t jol-rag-api:scan src/
	trivy image --severity HIGH,CRITICAL --exit-code 1 jol-rag-api:scan

## validate: Full local validation gate (lint + tests)
validate: lint test

## certs: Generate internal mTLS certificates (CA, server, client)
certs:
	bash scripts/tls/generate-mtls-certs.sh

## deploy: Deploy to rag-prod-lt01 via Ansible (requires vault-unlocked inventory)
deploy:
	ansible-playbook -i ansible/inventory/production.yml ansible/provision-rag.yml --limit rag-prod-lt01

## clean: Remove build/test artefacts
clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache .coverage htmlcov
	find . -type d -name __pycache__ -not -path './.venv/*' -exec rm -rf {} +
