# Hlídač vážení - běžné příkazy
PY ?= .venv/bin/python

.PHONY: install up down migrate reset simulate analyze report all test test-full

install:            ## virtuální prostředí a závislosti
	python3 -m venv .venv
	.venv/bin/pip install -U pip
	.venv/bin/pip install -e ".[dev]"

up:                 ## spustí databázi v Dockeru
	docker compose up -d --wait

down:               ## zastaví databázi (data zůstanou)
	docker compose down

migrate:            ## provede SQL migrace
	$(PY) -m hlidac migrate

reset:              ## smaže schéma a provede migrace znovu
	$(PY) -m hlidac reset

simulate:           ## nasimuluje provoz a uloží ho do databáze
	$(PY) -m hlidac simulate

analyze:            ## spustí detektory a uloží upozornění
	$(PY) -m hlidac analyze

report:             ## vytvoří out/report.html
	$(PY) -m hlidac report

all: up             ## vše od začátku: reset, simulace, analýza, report
	$(PY) -m hlidac all

test:               ## rychlé testy (+ databázové, pokud DB běží)
	$(PY) -m pytest

test-full:          ## i test nad celým obdobím (trvá pár minut)
	HLIDAC_FULL=1 $(PY) -m pytest
