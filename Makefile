SHELL := /bin/bash
.DEFAULT_GOAL := help

PYTHON := .venv/bin/python

.PHONY: help smoke run web refresh-index

help:
	@echo "Targets:"
	@echo "  make smoke               - run baseline smoke checks"
	@echo "  make run                 - run crawler with default config"
	@echo "  make web                 - start Next.js dev server"
	@echo "  make refresh-index       - sync auxiliary index snapshot data"

smoke:
	bash scripts/smoke_baseline.sh

run:
	$(PYTHON) -m src.main

web:
	cd web && npm run dev

refresh-index:
	bash scripts/refresh_index_source.sh
