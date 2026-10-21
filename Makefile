.PHONY: install test run demo docker

install:
	pip install -r requirements-dev.txt

test:
	pytest -q --cov=app --cov-report=term-missing

run:
	uvicorn app.main:app --reload

demo:
	python scripts/make_demo_data.py
	python -m app.cli validate-all --allow sjc01-r02-broken
	python -m app.cli render sjc01-r01 --out build
	-python -m app.cli drift sjc01-r01 sjc01-r01-leaf1 data/demo/leaf1-running.cfg
	python -m app.cli anomalies data/demo/metrics.json

docker:
	docker build -t netauto .
	docker run --rm -p 8000:8000 netauto
