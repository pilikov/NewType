SHELL := /bin/bash
.DEFAULT_GOAL := help

PYTHON := .venv/bin/python

.PHONY: help smoke run web mirror-check mirror-check-strict refresh-index

help:
	@echo "Targets:"
	@echo "  make smoke               - run baseline smoke checks"
	@echo "  make run                 - run crawler with default config"
	@echo "  make web                 - start Next.js dev server"
	@echo "  make refresh-index       - sync auxiliary index snapshot data"
	@echo "  make mirror-check        - report drift between src and typerelease-sync/src"
	@echo "  make mirror-check-strict - fail if drift exists"

smoke:
	bash scripts/smoke_baseline.sh

run:
	$(PYTHON) -m src.main

web:
	cd web && npm run dev

mirror-check:
	bash scripts/check_src_mirror.sh

mirror-check-strict:
	bash scripts/check_src_mirror.sh --strict

refresh-index:
	bash scripts/refresh_index_source.sh
