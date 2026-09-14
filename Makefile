.PHONY: up down logs test inject-failure recover benchmark ps

up:
	docker compose up --build -d
	@echo "Dashboard: http://localhost:3030"
	@echo "Prometheus: http://localhost:9090"
	@echo "Anomaly engine: http://localhost:8080/api/snapshot"

down:
	docker compose down

logs:
	docker compose logs -f --tail=200

ps:
	docker compose ps

test:
	docker compose exec -T anomaly-engine python -m pytest -q || python -m pytest -q anomaly-engine/tests

inject-failure:
	python failure-injection/inject_failure.py --service payment --duration 45 --rate 0.8 --type http_500

recover:
	python failure-injection/inject_failure.py --service payment --recover

benchmark:
	python failure-injection/benchmark.py --duration 35 --rate 0.85
