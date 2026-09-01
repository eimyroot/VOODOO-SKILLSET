.PHONY: cockpit verify test plan

PYTHON ?= python3
HOST ?= 127.0.0.1
PORT ?= 8787

cockpit:
	PYTHON="$(PYTHON)" VOODOO_HOST="$(HOST)" VOODOO_PORT="$(PORT)" bash scripts/cockpit.sh

test:
	PYTHONPATH=src $(PYTHON) -m unittest discover -s tests -p 'test_*.py' -v

verify:
	PYTHONPATH=src $(PYTHON) -m compileall -q src tests
	PYTHONPATH=src $(PYTHON) -m py_compile api/index.py tools/production_verify.py
	node --check web/app.js
	PYTHONPATH=src $(PYTHON) -m unittest discover -s tests -p 'test_*.py' -v

plan:
	PYTHONPATH=src $(PYTHON) -m voodoo_skillset.cli plan "Audit the GitHub repository, review security, implement fixes, test and verify" --mode ALL --connector github --tool filesystem-write --tool test-runner --tool isolated-runner --tool web-search
