#!/usr/bin/env bash
# =============================================================================
# @project    ELY — Exactly Like You
# @file       scripts/test-local.sh
# @brief      Monte une instance de test sur localhost, a cote de la prod
# =============================================================================
#
# POURQUOI CE SCRIPT (02/09/2026)
#
# Le circuit de test etait : pousser sur GitHub, tirer, `make build`, essayer
# sur https://ely.catalogmaker.fr. Le push n'y servait qu'a TRANSPORTER le code
# jusqu'a la copie de travail — `docker compose` construit depuis
# `./backend` et `./frontend`, jamais depuis un depot distant.
#
# Ce script coupe le detour : il monte une SECONDE pile, construite depuis un
# worktree de la branche demandee, sur d'autres ports, avec sa propre base.
# La prod continue de tourner pendant ce temps.
#
#   scripts/test-local.sh <branche>                  base vierge
#   scripts/test-local.sh <branche> --avec-donnees   copie de la base de prod
#   scripts/test-local.sh --arreter                  demonte l'instance de test
#
# ⚠️ COUT MEMOIRE, MESURE LE 02/09. La pile de test reclame ~6,5 Go (backend
# 5 Go + frontend 1,5 Go). Le Mac tournait ce jour-la a 31 Go utilises sur 32,
# avec 123 Mo libres et 16 Go de compresseur : les DEUX piles a la fois font
# swaper, et le swap degrade LM Studio (c'est la raison d'etre des `mem_limit`
# du compose). Le reflexe qui marche :
#
#     make down && scripts/test-local.sh <branche> --avec-donnees
#     …  essais sur http://localhost:8080  …
#     scripts/test-local.sh --arreter && make up
#
# Meme budget memoire, isolation complete, et la prod revient telle quelle.
# Le domaine est simplement indisponible pendant l'essai.
#
# ⚠️ Pour un test qui n'a PAS besoin d'isolation, il y a plus court — fusionner
# la branche dans ta copie et reconstruire la pile existante :
#     git merge --no-ff <branche> && make build
# Meme URL, vraies donnees, zero RAM en plus. Mais les migrations s'appliquent
# a ta VRAIE base : c'est le compromis.

set -euo pipefail

RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WT="$RACINE/.claude/worktrees/test-local"
PROJET="ely-test"

PORT_HTTP=8080      # nginx — c'est l'URL que tu ouvres
PORT_FRONT=3100
PORT_BACK=8100
PORT_QDRANT=6433

# ── Arret ────────────────────────────────────────────────────────────────────
if [ "${1:-}" = "--arreter" ]; then
    if [ -d "$WT" ]; then
        docker compose -p "$PROJET" --project-directory "$WT" down -v
    else
        docker compose -p "$PROJET" down -v 2>/dev/null || true
    fi
    git -C "$RACINE" worktree remove --force "$WT" 2>/dev/null || true
    echo "Instance de test demontee (conteneurs, volumes et worktree)."
    exit 0
fi

BRANCHE="${1:-}"
if [ -z "$BRANCHE" ]; then
    echo "usage : scripts/test-local.sh <branche> [--avec-donnees]" >&2
    echo "        scripts/test-local.sh --arreter" >&2
    exit 1
fi
AVEC_DONNEES="${2:-}"

if ! git -C "$RACINE" rev-parse --verify --quiet "$BRANCHE" >/dev/null; then
    echo "Branche introuvable : $BRANCHE" >&2
    echo >&2
    # ⚠️ `--no-pager` (02/09/2026). Sans lui, `git branch` ouvre `less` des que
    # la liste depasse la hauteur du terminal — ce depot a plus de 60 branches.
    # Le script, lui, etait deja termine : l'utilisateur se retrouvait coince
    # dans un pager qui ignore Ctrl+C, sans rien pour lui dire d'appuyer sur q.
    # Un message d'erreur qui bloque le terminal est pire que pas de message.
    #
    # `-v` trie par date de commit decroissante et `head` coupe : les branches
    # utiles sont les recentes, les 60 autres sont du bruit.
    echo "Les 10 branches les plus recentes :" >&2
    git -C "$RACINE" --no-pager branch --sort=-committerdate \
        --format='  %(refname:short)   (%(committerdate:relative))' \
        2>/dev/null | head -10 >&2
    echo >&2
    echo "Pour tester ce qui est sur GitHub : scripts/test-local.sh origin/main" >&2
    exit 1
fi

# ── Le worktree ──────────────────────────────────────────────────────────────
# `--detach` volontairement : un worktree qui CHECKOUT la branche l'empeche
# d'etre utilisee ailleurs (y compris par l'agent qui travaille encore dessus).
# Detache, on prend l'etat de la branche sans la reserver.
git -C "$RACINE" worktree remove --force "$WT" 2>/dev/null || true
git -C "$RACINE" worktree add --detach "$WT" "$BRANCHE" >/dev/null
echo "→ worktree sur $(git -C "$WT" log --oneline -1)"

# ── L'environnement de la pile de test ───────────────────────────────────────
# On repart du `.env` de prod (cles LLM, jetons, secrets : identiques) et on
# reecrit UNIQUEMENT ce qui doit changer pour du localhost en clair.
cp "$RACINE/.env" "$WT/.env"

_poser() {  # _poser CLE VALEUR — remplace la ligne si elle existe, l'ajoute sinon
    local cle="$1" val="$2" f="$WT/.env"
    if grep -qE "^${cle}=" "$f"; then
        # Delimiteur `|` : les valeurs contiennent des `/` (URL).
        sed -i '' "s|^${cle}=.*|${cle}=${val}|" "$f"
    else
        # ⚠️ Un `.env` qui ne finit PAS par un saut de ligne colle l'ajout a sa
        # derniere ligne : on obtient `SLM_TIMEOUT=25ELY_HTTP_PORT=8080`, une
        # cle silencieusement perdue et une valeur silencieusement corrompue.
        # Attrape en test le 02/09 — le port de test n'etait pas applique et la
        # pile essayait de se poser sur le 80 de la prod.
        [ -s "$f" ] && [ -n "$(tail -c 1 "$f")" ] && printf '\n' >> "$f"
        printf '%s=%s\n' "$cle" "$val" >> "$f"
    fi
}

_poser COMPOSE_PROJECT_NAME "$PROJET"
_poser ELY_HTTP_PORT     "$PORT_HTTP"
_poser ELY_FRONTEND_PORT "$PORT_FRONT"
_poser ELY_BACKEND_PORT  "$PORT_BACK"
_poser ELY_QDRANT_PORT   "$PORT_QDRANT"

# ⚠️ NEXT_PUBLIC_* est un ARGUMENT DE CONSTRUCTION : la valeur est gravee dans
# le bundle Next.js. Laisser le domaine ici ferait taper le navigateur sur la
# PROD depuis l'instance de test, sans le moindre message d'erreur.
_poser NEXT_PUBLIC_API_URL "http://localhost:$PORT_HTTP"
_poser NEXT_PUBLIC_WS_URL  "ws://localhost:$PORT_HTTP"
_poser FRONTEND_URL        "http://localhost:$PORT_HTTP"
_poser BACKEND_URL         "http://localhost:$PORT_HTTP"

# ⚠️ Sans ca, la connexion est CASSEE et le symptome ne dit pas pourquoi : un
# cookie `Secure` n'est pas pose par le navigateur sur du `http://`, donc le
# jeton de rafraichissement disparait et on est deconnecte au premier refresh.
_poser COOKIE_SECURE false
# ⚠️ Et il faut vider CORS_ORIGINS : `config.py` REACTIVE cookie_secure tout
# seul des qu'il y voit un `https://` (auto-enable, ligne ~404).
_poser CORS_ORIGINS ""

# ⚠️ La prod expose ~/.ssh au conteneur (outils ssh_*). Une pile de test n'a
# aucune raison de voir tes cles privees : on la renvoie sur le dossier vide.
_poser SSH_KEYS_PATH "./data/ssh"

mkdir -p "$WT/data/db" "$WT/data/uploads" "$WT/data/ssh"

# ── Les donnees ──────────────────────────────────────────────────────────────
if [ "$AVEC_DONNEES" = "--avec-donnees" ]; then
    echo "→ copie de la base de prod (~$(du -sh "$RACINE/data/db" | cut -f1))…"
    # `cp` d'une base SQLite VIVANTE peut copier un instantane incoherent
    # (journal WAL non replaye). `.backup` de sqlite3 prend un verrou et rend
    # un fichier sain, meme pendant que la prod ecrit.
    if command -v sqlite3 >/dev/null; then
        sqlite3 "$RACINE/data/db/cyberentity.db" \
            ".backup '$WT/data/db/cyberentity.db'"
    else
        echo "  ⚠️ sqlite3 absent : copie brute, l'instantane peut etre incoherent"
        cp "$RACINE/data/db/cyberentity.db" "$WT/data/db/cyberentity.db"
    fi
    cp -R "$RACINE/data/uploads/." "$WT/data/uploads/" 2>/dev/null || true
    echo "  → tes comptes et conversations sont dans l'instance de test."
    echo "  ⚠️ La memoire vectorielle (Qdrant), elle, repart VIDE : ses volumes"
    echo "     sont propres au projet compose. Les faits reinjectes viendront"
    echo "     de SQLite, pas du RAG."
else
    echo "→ base VIERGE. Cree un compte apres le demarrage :"
    echo "   docker compose -p $PROJET --project-directory $WT exec -T backend \\"
    echo "     bash -c 'cd /app && PYTHONPATH=/app uv run --no-sync python scripts/create_admin.py'"
fi

# ── Le demarrage ─────────────────────────────────────────────────────────────
echo "→ construction et demarrage (compte quelques minutes au premier coup)…"
docker compose -p "$PROJET" --project-directory "$WT" up -d --build

cat <<FIN

  Instance de test :  http://localhost:$PORT_HTTP
  Prod, intacte    :  https://ely.catalogmaker.fr

  Journaux   docker compose -p $PROJET --project-directory $WT logs -f backend
  Arret      scripts/test-local.sh --arreter

FIN
