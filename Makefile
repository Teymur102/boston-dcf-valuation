PY := .venv/bin/python
TICKER ?= TJX

.PHONY: all setup run refresh test clean

all: run test

setup:
	python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt

run:
	$(PY) -m dcf run $(TICKER) --readme

refresh:
	$(PY) -m dcf run $(TICKER) --readme --refresh

test:
	$(PY) -m pytest
