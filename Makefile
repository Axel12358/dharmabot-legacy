.PHONY: install run loop test salud clean

install:
	pip install -r requirements.txt
	playwright install

run:
	python main.py

loop:
	./run_loop_completar.sh

test:
	@python3 -m pytest tests/ 2>/dev/null || python3 tests/test_minero_breaker.py

# Healthcheck runtime: prueba constante del pipeline (CSV, loop, SERP, watchdog).
salud:
	python3 salud.py

clean:
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete
	rm -f *.log *.csv *.tmp
