.PHONY: up down restart build logs ps slm-pull slm-logs slm-enable slm-disable

# Charge le .env et démarre tous les services
up:
	docker compose up -d

# Arrête tous les services
down:
	docker compose down

# Rebuild + redémarre un service (ex: make restart s=backend)
restart:
	docker compose up -d --build $(s)

# Rebuild et redémarre tout
build:
	docker compose up -d --build

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
