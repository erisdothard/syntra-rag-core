.PHONY: install test lint ingest serve regression clean

install:
	pip install -e .

test:
	python -m pytest tests/ -v --cov=core --cov=clients --cov-report=term-missing --tb=short

lint:
	ruff check .

ingest:
	python scripts/ingest.py

serve:
	python -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

mcp:
	python -m core.mcp_server

regression:
	python scripts/regression.py

neutrality:
	@if grep -ri "loinc\|snomed\|fhir\|hl7\|observation" core/; then \
		echo "FAIL: Domain terms found in core/"; exit 1; \
	fi
	@echo "PASS: core/ is domain-neutral"

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .pytest_cache htmlcov .coverage
