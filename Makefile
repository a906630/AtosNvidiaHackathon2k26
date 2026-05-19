SHELL := /bin/bash

COMPOSE := docker compose
SERVICE := czk-api
API_URL ?= http://localhost:8080

.PHONY: help build up up-d down restart logs ps pull smoke

help:
	@echo "Available targets:"
	@echo "  make build    - Build container image"
	@echo "  make up       - Start stack in foreground"
	@echo "  make up-d     - Start stack in background"
	@echo "  make down     - Stop and remove stack"
	@echo "  make restart  - Restart stack (detached)"
	@echo "  make logs     - Tail logs from $(SERVICE)"
	@echo "  make ps       - Show compose service status"
	@echo "  make pull     - Pull base images"
	@echo "  make smoke    - Run basic health smoke test"

build:
	$(COMPOSE) build

up:
	$(COMPOSE) up

up-d:
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

restart: down up-d

logs:
	$(COMPOSE) logs -f $(SERVICE)

ps:
	$(COMPOSE) ps

pull:
	$(COMPOSE) pull

smoke:
	curl -fsS $(API_URL)/health
	curl -fsS $(API_URL)/viz/graph/json

