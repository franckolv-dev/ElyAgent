.PHONY: up down restart build logs ps slm-pull slm-logs slm-enable slm-disable

# Charge le .env et démarre tous les services
up:
	docker compose up -d

# Arrête tous les services
down:
	docker compose down

# Rebuild + redémarre un service (ex: make restart s=backend)
# Restart nginx after backend/frontend restart to re-resolve upstream DNS
# (Docker gives a new IP each time a container is recreated, nginx caches
# the old one and returns 502 "Host is unreachable" until reloaded).
restart:
	docker compose up -d --build $(s)
	@if [ "$(s)" = "backend" ] || [ "$(s)" = "frontend" ]; then \
		echo "→ Reloading nginx to re-resolve upstream DNS..."; \
		docker restart cyberentity-nginx; \
	fi

# Rebuild et redémarre tout (nginx restart automatique à la fin)
build:
	docker compose up -d --build
	@docker restart cyberentity-nginx

# Supprime tous les services Ollama/SLM orphelins (container Ollama a été retiré)
# Ne supprime pas l'Ollama natif du Mac (qui reste utilisé via host.docker.internal)
ollama-cleanup:
	@docker rm -f cyberentity-ollama cyberentity-ollama-init 2>/dev/null || true
	@docker volume rm physicalagent-master_ollama-data 2>/dev/null || true
	@echo "Container Ollama Docker nettoyé (Ollama du Mac intact)"

# Logs d'un service (ex: make logs s=backend)
logs:
	docker compose logs -f $(s)

# État des containers
ps:
	docker compose ps

# ── SLM / Ollama ──────────────────────────────────────────────────────

# Pull (ou mettre à jour) le modèle SLM dans Ollama
slm-pull:
	docker compose exec ollama ollama pull $(or $(m),qwen2.5:3b-instruct)

# Logs du service Ollama
slm-logs:
	docker compose logs -f ollama

# Activer le SLM (modifier le .env puis rebuilder le backend)
slm-enable:
	@sed -i 's/^SLM_ENABLED=.*/SLM_ENABLED=true/' .env || echo "SLM_ENABLED=true" >> .env
	docker compose up -d --build backend

# Désactiver le SLM
slm-disable:
	@sed -i 's/^SLM_ENABLED=.*/SLM_ENABLED=false/' .env || echo "SLM_ENABLED=false" >> .env
	docker compose up -d --build backend
