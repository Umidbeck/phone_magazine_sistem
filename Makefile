# Makefile - Production Deployment Helper

.PHONY: help build up down restart logs shell migrate collectstatic backup restore clean

# Colors
RED=\033[0;31m
GREEN=\033[0;32m
YELLOW=\033[1;33m
NC=\033[0m # No Color

help: ## Show this help message
	@echo "$(GREEN)Phone Magazine System - Deployment Commands$(NC)"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(YELLOW)%-20s$(NC) %s\n", $$1, $$2}'

# ==================================
# SETUP
# ==================================

setup: ## Initial setup - copy .env and create directories
	@echo "$(GREEN)Setting up project...$(NC)"
	@cp -n .env.example .env || true
	@mkdir -p logs backups nginx/logs
	@chmod +x entrypoint.sh
	@echo "$(GREEN)✓ Setup complete! Edit .env file with your settings.$(NC)"

# ==================================
# DOCKER COMMANDS
# ==================================

build: ## Build Docker images
	@echo "$(GREEN)Building Docker images...$(NC)"
	docker-compose build --no-cache

up: ## Start all services
	@echo "$(GREEN)Starting services...$(NC)"
	docker-compose up -d
	@echo "$(GREEN)✓ Services started!$(NC)"
	@echo "$(YELLOW)Run 'make logs' to see logs$(NC)"

down: ## Stop all services
	@echo "$(RED)Stopping services...$(NC)"
	docker-compose down
	@echo "$(GREEN)✓ Services stopped!$(NC)"

restart: ## Restart all services
	@echo "$(YELLOW)Restarting services...$(NC)"
	docker-compose restart
	@echo "$(GREEN)✓ Services restarted!$(NC)"

logs: ## Show logs (use: make logs SERVICE=web)
	@docker-compose logs -f $(SERVICE)

ps: ## Show running containers
	@docker-compose ps

# ==================================
# DATABASE
# ==================================

migrate: ## Run database migrations
	@echo "$(GREEN)Running migrations...$(NC)"
	docker-compose exec web python manage.py migrate
	@echo "$(GREEN)✓ Migrations complete!$(NC)"

makemigrations: ## Create new migrations
	@echo "$(GREEN)Creating migrations...$(NC)"
	docker-compose exec web python manage.py makemigrations
	@echo "$(GREEN)✓ Migrations created!$(NC)"

shell: ## Open Django shell
	docker-compose exec web python manage.py shell

dbshell: ## Open database shell
	docker-compose exec web python manage.py dbshell

createsuperuser: ## Create Django superuser
	docker-compose exec web python manage.py createsuperuser

# ==================================
# STATIC FILES
# ==================================

collectstatic: ## Collect static files
	@echo "$(GREEN)Collecting static files...$(NC)"
	docker-compose exec web python manage.py collectstatic --noinput
	@echo "$(GREEN)✓ Static files collected!$(NC)"

# ==================================
# BACKUP & RESTORE
# ==================================

backup: ## Backup database
	@echo "$(GREEN)Creating database backup...$(NC)"
	@mkdir -p backups
	@docker-compose exec -T db pg_dump -U $(shell grep POSTGRES_USER .env | cut -d '=' -f2) \
		$(shell grep POSTGRES_DB .env | cut -d '=' -f2) > backups/backup_$(shell date +%Y%m%d_%H%M%S).sql
	@echo "$(GREEN)✓ Backup created in backups/ directory$(NC)"

restore: ## Restore database (use: make restore FILE=backup.sql)
	@echo "$(YELLOW)Restoring database from $(FILE)...$(NC)"
	@docker-compose exec -T db psql -U $(shell grep POSTGRES_USER .env | cut -d '=' -f2) \
		$(shell grep POSTGRES_DB .env | cut -d '=' -f2) < $(FILE)
	@echo "$(GREEN)✓ Database restored!$(NC)"

backup-media: ## Backup media files
	@echo "$(GREEN)Backing up media files...$(NC)"
	@mkdir -p backups
	@tar -czf backups/media_$(shell date +%Y%m%d_%H%M%S).tar.gz -C . media/
	@echo "$(GREEN)✓ Media backup created!$(NC)"

# ==================================
# DEPLOYMENT
# ==================================

deploy: ## Full deployment (build, up, migrate, collectstatic)
	@echo "$(GREEN)Starting full deployment...$(NC)"
	@make build
	@make up
	@sleep 10
	@make migrate
	@make collectstatic
	@echo "$(GREEN)✓ Deployment complete!$(NC)"

redeploy: ## Redeploy (down, pull latest, deploy)
	@echo "$(YELLOW)Redeploying application...$(NC)"
	@make down
	@git pull
	@make deploy
	@echo "$(GREEN)✓ Redeployment complete!$(NC)"

# ==================================
# SSL CERTIFICATES
# ==================================

ssl-setup: ## Initial SSL certificate setup
	@echo "$(GREEN)Setting up SSL certificate...$(NC)"
	@docker-compose run --rm certbot certonly --webroot \
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
	@docker-compose exec certbot certbot renew
	@docker-compose exec nginx nginx -s reload
	@echo "$(GREEN)✓ SSL certificates renewed!$(NC)"

# ==================================
# MAINTENANCE
# ==================================

clean: ## Clean Docker resources
	@echo "$(RED)Cleaning Docker resources...$(NC)"
	docker-compose down -v
	docker system prune -f
	@echo "$(GREEN)✓ Cleanup complete!$(NC)"

update: ## Update Docker images
	@echo "$(GREEN)Updating Docker images...$(NC)"
	docker-compose pull
	@echo "$(GREEN)✓ Images updated!$(NC)"

health: ## Check services health
	@echo "$(GREEN)Checking services health...$(NC)"
	@docker-compose ps
	@echo ""
	@docker-compose exec web python manage.py check
	@echo "$(GREEN)✓ Health check complete!$(NC)"

# ==================================
# MONITORING
# ==================================

stats: ## Show container stats
	docker stats $(shell docker-compose ps -q)

disk: ## Show disk usage
	@echo "$(GREEN)Docker disk usage:$(NC)"
	@docker system df
	@echo ""
	@echo "$(GREEN)Volume sizes:$(NC)"
	@docker volume ls -q | xargs docker volume inspect | grep -E 'Name|Mountpoint'

# ==================================
# DEVELOPMENT
# ==================================

dev: ## Start in development mode
	@echo "$(GREEN)Starting in development mode...$(NC)"
	docker-compose -f docker-compose.yml -f docker-compose.dev.yml up

test: ## Run tests
	docker-compose exec web python manage.py test

shell-web: ## Shell into web container
	docker-compose exec web /bin/bash

shell-db: ## Shell into database container
	docker-compose exec db /bin/bash

shell-nginx: ## Shell into nginx container
	docker-compose exec nginx /bin/sh