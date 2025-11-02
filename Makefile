# Makefile - Production Deployment Helper (docker compose v2 friendly)

.PHONY: help setup build up down restart logs ps migrate makemigrations \
        shell dbshell createsuperuser collectstatic backup restore \
        backup-media deploy redeploy ssl-setup ssl-renew clean update \
        health stats disk dev test shell-web shell-db shell-nginx

# ============
# Colors
# ============
RED=\033[0;31m
GREEN=\033[0;32m
YELLOW=\033[1;33m
NC=\033[0m # No Color

# ============
# Compose auto-detect
# If docker-compose exists -> use it, else use `docker compose`
# ============
COMPOSE := $(shell command -v docker-compose >/dev/null 2>&1 && echo docker-compose || echo docker compose)

# Defaults
SERVICE ?= web
FILE ?=

help: ## Show this help message
	@echo "$(GREEN)Phone Magazine System - Deployment Commands$(NC)"
	@echo ""
	@grep -E '^[a-zA-Z0-9._-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(YELLOW)%-20s$(NC) %s\n", $$1, $$2}'

# ==================================
# SETUP
# ==================================

setup: ## Initial setup - copy .env and create directories
	@echo "$(GREEN)Setting up project...$(NC)"
	@[ -f .env ] || cp -n .env.example .env || true
	@mkdir -p logs backups nginx/logs
	@[ -f entrypoint.sh ] && chmod +x entrypoint.sh || true
	@echo "$(GREEN)✓ Setup complete! Edit .env with your settings.$(NC)"

# ==================================
# DOCKER COMMANDS
# ==================================

build: ## Build Docker images
	@echo "$(GREEN)Building Docker images...$(NC)"
	@$(COMPOSE) build --no-cache

up: ## Start all services
	@echo "$(GREEN)Starting services...$(NC)"
	@$(COMPOSE) up -d
	@echo "$(GREEN)✓ Services started!$(NC)"
	@echo "$(YELLOW)Run 'make logs' to see logs$(NC)"

down: ## Stop all services
	@echo "$(RED)Stopping services...$(NC)"
	@$(COMPOSE) down
	@echo "$(GREEN)✓ Services stopped!$(NC)"

restart: ## Restart all services
	@echo "$(YELLOW)Restarting services...$(NC)"
	@$(COMPOSE) restart
	@echo "$(GREEN)✓ Services restarted!$(NC)"

logs: ## Show logs (use: make logs SERVICE=web)
	@$(COMPOSE) logs -f $(SERVICE)

ps: ## Show running containers
	@$(COMPOSE) ps

# ==================================
# DATABASE
# ==================================

migrate: ## Run database migrations
	@echo "$(GREEN)Running migrations...$(NC)"
	@$(COMPOSE) exec -T web python manage.py migrate
	@echo "$(GREEN)✓ Migrations complete!$(NC)"

makemigrations: ## Create new migrations
	@echo "$(GREEN)Creating migrations...$(NC)"
	@$(COMPOSE) exec -T web python manage.py makemigrations
	@echo "$(GREEN)✓ Migrations created!$(NC)"

shell: ## Open Django shell
	@$(COMPOSE) exec -T web python manage.py shell

dbshell: ## Open database shell
	@$(COMPOSE) exec -T web python manage.py dbshell

createsuperuser: ## Create Django superuser
	@$(COMPOSE) exec -T web python manage.py createsuperuser

# ==================================
# STATIC FILES
# ==================================

collectstatic: ## Collect static files
	@echo "$(GREEN)Collecting static files...$(NC)"
	@$(COMPOSE) exec -T web python manage.py collectstatic --noinput
	@echo "$(GREEN)✓ Static files collected!$(NC)"

# ==================================
# BACKUP & RESTORE
# ==================================

backup: ## Backup database
	@echo "$(GREEN)Creating database backup...$(NC)"
	@mkdir -p backups
	@USER=$$(grep -E '^POSTGRES_USER=' .env | tail -n1 | cut -d '=' -f2); \
	DB=$$(grep -E '^POSTGRES_DB=' .env | tail -n1 | cut -d '=' -f2); \
	if [ -z "$$USER" ] || [ -z "$$DB" ]; then \
	  echo "$(RED)POSTGRES_USER/POSTGRES_DB topilmadi (.env ni tekshiring)$(NC)"; exit 1; \
	fi; \
	$(COMPOSE) exec -T db pg_dump -U $$USER $$DB > backups/backup_$$(date +%Y%m%d_%H%M%S).sql
	@echo "$(GREEN)✓ Backup created in backups/ directory$(NC)"

restore: ## Restore database (use: make restore FILE=backups/backup_xxx.sql)
	@test -n "$(FILE)" || (echo "$(RED)FILE parameter is required: make restore FILE=backups/backup.sql$(NC)"; exit 1)
	@echo "$(YELLOW)Restoring database from $(FILE)...$(NC)"
	@USER=$$(grep -E '^POSTGRES_USER=' .env | tail -n1 | cut -d '=' -f2); \
	DB=$$(grep -E '^POSTGRES_DB=' .env | tail -n1 | cut -d '=' -f2); \
	if [ -z "$$USER" ] || [ -z "$$DB" ]; then \
	  echo "$(RED)POSTGRES_USER/POSTGRES_DB topilmadi (.env ni tekshiring)$(NC)"; exit 1; \
	fi; \
	$(COMPOSE) exec -T db psql -U $$USER $$DB < $(FILE)
	@echo "$(GREEN)✓ Database restored!$(NC)"

backup-media: ## Backup media files
	@echo "$(GREEN)Backing up media files...$(NC)"
	@mkdir -p backups
	@tar -czf backups/media_$$(date +%Y%m%d_%H%M%S).tar.gz -C . media/ 2>/dev/null || true
	@echo "$(GREEN)✓ Media backup created!$(NC)"

# ==================================
# DEPLOYMENT
# ==================================

deploy: ## Full deployment (build, up, migrate, collectstatic)
	@echo "$(GREEN)Starting full deployment...$(NC)"
	@$(MAKE) build
	@$(MAKE) up
	@sleep 10
	@$(MAKE) migrate
	@$(MAKE) collectstatic
	@echo "$(GREEN)✓ Deployment complete!$(NC)"

redeploy: ## Redeploy (down, pull latest, deploy)
	@echo "$(YELLOW)Redeploying application...$(NC)"
	@$(MAKE) down
	@git pull
	@$(MAKE) deploy
	@echo "$(GREEN)✓ Redeployment complete!$(NC)"

# ==================================
# SSL CERTIFICATES
# (Assumes you have certbot & nginx services in compose)
# ==================================

ssl-setup: ## Initial SSL certificate setup
	@echo "$(GREEN)Setting up SSL certificate...$(NC)"
	@$(COMPOSE) run --rm certbot certonly --webroot \
		-w /var/www/certbot \
		-d yourdomain.com \
		-d www.yourdomain.com \
		--email your-email@example.com \
		--agree-tos \
		--no-eff-email
	@echo "$(GREEN)✓ SSL certificate obtained!$(NC)"
	@echo "$(YELLOW)Now uncomment HTTPS server block in nginx/conf.d/default.conf$(NC)"

ssl-renew: ## Renew SSL certificates
	@echo "$(GREEN)Renewing SSL certificates...$(NC)"
	@$(COMPOSE) exec -T certbot certbot renew
	@$(COMPOSE) exec -T nginx nginx -s reload
	@echo "$(GREEN)✓ SSL certificates renewed!$(NC)"

# ==================================
# MAINTENANCE
# ==================================

clean: ## Clean Docker resources
	@echo "$(RED)Cleaning Docker resources...$(NC)"
	@$(COMPOSE) down -v
	@docker system prune -f
	@echo "$(GREEN)✓ Cleanup complete!$(NC)"

update: ## Update Docker images
	@echo "$(GREEN)Updating Docker images...$(NC)"
	@$(COMPOSE) pull
	@echo "$(GREEN)✓ Images updated!$(NC)"

health: ## Check services health
	@echo "$(GREEN)Checking services health...$(NC)"
	@$(COMPOSE) ps
	@echo ""
	@$(COMPOSE) exec -T web python manage.py check
	@echo "$(GREEN)✓ Health check complete!$(NC)"

# ==================================
# MONITORING
# ==================================

stats: ## Show container stats
	@CONTAINERS=$$($(COMPOSE) ps -q); \
	if [ -z "$$CONTAINERS" ]; then echo "$(YELLOW)No running containers$(NC)"; exit 0; fi; \
	docker stats $$CONTAINERS

disk: ## Show disk usage
	@echo "$(GREEN)Docker disk usage:$(NC)"
	@docker system df
	@echo ""
	@echo "$(GREEN)Volume sizes:$(NC)"
	@docker volume ls -q | xargs docker volume inspect 2>/dev/null | grep -E 'Name|Mountpoint' || true

# ==================================
# DEVELOPMENT
# ==================================

dev: ## Start in development mode (compose override)
	@echo "$(GREEN)Starting in development mode...$(NC)"
	@$(COMPOSE) -f docker-compose.yml -f docker-compose.dev.yml up

test: ## Run tests
	@$(COMPOSE) exec -T web python manage.py test

shell-web: ## Shell into web container
	@$(COMPOSE) exec -T web /bin/bash

shell-db: ## Shell into database container
	@$(COMPOSE) exec -T db /bin/bash

shell-nginx: ## Shell into nginx container
	@$(COMPOSE) exec -T nginx /bin/sh
