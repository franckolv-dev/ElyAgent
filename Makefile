.PHONY: up down restart build logs ps

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
