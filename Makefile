.PHONY: up down restart build logs ps create-admin ollama-cleanup slm-enable slm-disable

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
		docker compose exec nginx nginx -s reload; \
	fi

# Rebuild et redémarre tout (nginx restart automatique à la fin)
build:
	docker compose up -d --build
	@docker compose exec nginx nginx -s reload

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

# NOTE : the in-Docker `ollama` service was removed in favour of the
# host's native Ollama (better GPU/Metal acceleration on Mac, no model
# duplication). To pull/manage Ollama models, use the host CLI directly:
#   ollama pull qwen2.5:7b-instruct
#   ollama list
# The previous `slm-pull`, `slm-logs` Makefile targets have been removed.

# Activer le SLM (modifier le .env puis rebuilder le backend)
slm-enable:
	@sed -i 's/^SLM_ENABLED=.*/SLM_ENABLED=true/' .env || echo "SLM_ENABLED=true" >> .env
	docker compose up -d --build backend

# Désactiver le SLM
slm-disable:
	@sed -i 's/^SLM_ENABLED=.*/SLM_ENABLED=false/' .env || echo "SLM_ENABLED=false" >> .env
	docker compose up -d --build backend

# ── Convenience : create the first admin user ─────────────────────────
# Usage : make create-admin USER=franck PASS='YourStr0ng!Pass' EMAIL=you@example.com
# Note : the FIRST user to register via the web UI is also auto-promoted
# to admin, so this target is only needed for headless / scripted setups.
create-admin:
	@if [ -z "$(USER)" ] || [ -z "$(PASS)" ]; then \
		echo "Usage: make create-admin USER=<name> PASS=<pwd> [EMAIL=<email>]"; exit 1; \
	fi
	@docker exec cyberentity-backend bash -c "cd /app && PYTHONPATH=/app uv run --no-sync python /app/scripts/create_admin.py \
		--username '$(USER)' --password '$(PASS)' --email '${EMAIL:-$(USER)@local}'"
