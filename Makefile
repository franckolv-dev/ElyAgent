.PHONY: up down restart build logs ps create-admin ollama-cleanup slm-enable slm-disable egress-reload

# Charge le .env et démarre tous les services
up:
	docker compose up -d

# Arrête tous les services
down:
	docker compose down

# Rebuild + redémarre un service (ex: make restart s=backend)
# On RECRÉE nginx (au lieu de `nginx -s reload`) après backend/frontend :
#  1) DNS — Docker donne une nouvelle IP à chaque recreate ; recréer nginx le
#     force à re-résoudre l'upstream (sinon 502 "Host is unreachable").
#  2) Robustesse inode — `nginx -s reload` lit la conf via l'inode épinglé au
#     démarrage du conteneur ; après un `git pull` qui remplace
#     config/nginx/default.conf, cet inode est périmé (cf. mount dossier dans
#     docker-compose.yml). Un recreate repart sur le fichier courant à coup sûr.
# `--no-deps` : recrée nginx SEUL (sans `--no-deps`, compose recrée aussi le
# frontend dont nginx dépend → 502 transitoire le temps qu'il redémarre).
# Coût : ~1 s d'indispo nginx par déploiement, acceptable pour une instance perso.
restart:
	docker compose up -d --build $(s)
	@if [ "$(s)" = "backend" ] || [ "$(s)" = "frontend" ]; then \
		echo "→ Recréation de nginx (re-résolution DNS + relecture conf)..."; \
		docker compose up -d --no-deps --force-recreate nginx; \
	fi

# Rebuild et redémarre tout (nginx recréé à la fin : DNS + conf à jour)
build:
	docker compose up -d --build
	@docker compose up -d --no-deps --force-recreate nginx

# Applique un changement de sandbox/squid/squid.conf (ex: ajout d'un domaine
# egress). On RECRÉE le conteneur egress-proxy au lieu d'un `squid -k
# reconfigure` :
#  1) Le mount DOSSIER (cf. docker-compose.yml) supprime déjà l'inode périmé,
#     mais un recreate garantit la relecture COMPLÈTE de la conf (un
#     reconfigure peut relire une version partielle / dépendre du timing).
#  2) `--no-deps` : recrée egress-proxy SEUL (le service `sandbox` qui en
#     dépend n'est pas redémarré inutilement).
# Coût : ~1 s d'indispo du proxy egress, négligeable (chaîne sandbox idle).
egress-reload:
	docker compose up -d --no-deps --force-recreate egress-proxy

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
	@docker compose exec -T backend bash -c "cd /app && PYTHONPATH=/app uv run --no-sync python /app/scripts/create_admin.py \
		--username '$(USER)' --password '$(PASS)' --email '${EMAIL:-$(USER)@local}'"
