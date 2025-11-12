DC = docker compose

.PHONY: up down reload-ui

build:
	$(DC) build

down:
	$(DC) down

reload-ui:
	$(DC) restart api
