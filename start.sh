#!/usr/bin/env bash
# ── ELY — Script de lancement local (Mac Studio) ──────────────────────
# Usage :
#   ./start.sh          → démarre backend + frontend
#   ./start.sh stop     → arrête backend + frontend
#   ./start.sh restart  → redémarre tout
#   ./start.sh logs     → tail des deux logs
#   ./start.sh status   → état des services

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"
FRONTEND_DIR="$SCRIPT_DIR/frontend"
LOG_DIR="$SCRIPT_DIR/logs"
BACKEND_PID="$LOG_DIR/backend.pid"
FRONTEND_PID="$LOG_DIR/frontend.pid"
BACKEND_LOG="$LOG_DIR/backend.log"
FRONTEND_LOG="$LOG_DIR/frontend.log"

mkdir -p "$LOG_DIR"

# ── Détection Python 3.12+ ────────────────────────────────────────────
find_python() {
    for py in python3.13 python3.12 python3; do
        if command -v "$py" &>/dev/null; then
            ver=$("$py" -c 'import sys; print(sys.version_info[:2])')
            if "$py" -c 'import sys; sys.exit(0 if sys.version_info >= (3,12) else 1)' 2>/dev/null; then
                echo "$py"
                return 0
            fi
        fi
    done
    # Homebrew paths (Apple Silicon + Intel)
    for p in /opt/homebrew/opt/python@3.13/bin/python3.13 /opt/homebrew/opt/python@3.12/bin/python3.12 /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3.12 /usr/local/bin/python3.13 /usr/local/bin/python3.12; do
        if [ -x "$p" ]; then echo "$p"; return 0; fi
    done
    echo ""
}

PYTHON=$(find_python)

start_qdrant() {
    echo "→ Démarrage Qdrant (Docker)…"
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^qdrant$"; then
        echo "  Qdrant déjà en cours."
    elif docker ps -a --format '{{.Names}}' 2>/dev/null | grep -q "^qdrant$"; then
        docker start qdrant
        echo "  Qdrant redémarré."
    else
        docker run -d \
            --name qdrant \
            --restart unless-stopped \
            -p 6333:6333 \
            -v qdrant_storage:/qdrant/storage \
            qdrant/qdrant
        echo "  Qdrant lancé."
    fi
}

start_backend() {
    echo "→ Démarrage backend FastAPI…"
    if [ -f "$BACKEND_PID" ] && kill -0 "$(cat "$BACKEND_PID")" 2>/dev/null; then
        echo "  Backend déjà en cours (PID $(cat "$BACKEND_PID"))."
        return
    fi

    if [ -z "$PYTHON" ]; then
        echo "✗ Python 3.12+ introuvable. Installe-le via Homebrew : brew install python@3.12"
        exit 1
    fi

    # Cherche uv dans les emplacements standards
    UV=$(command -v uv 2>/dev/null || echo "$HOME/.local/bin/uv")
    if [ ! -x "$UV" ]; then
        echo "✗ uv introuvable. Installe-le : curl -LsSf https://astral.sh/uv/install.sh | sh"
        exit 1
    fi

    cd "$BACKEND_DIR"
    nohup "$UV" run uvicorn app.main:app --host 0.0.0.0 --port 8000 \
        >> "$BACKEND_LOG" 2>&1 &
    echo $! > "$BACKEND_PID"
    echo "  Backend démarré (PID $!, log: $BACKEND_LOG)"
}

start_frontend() {
    echo "→ Démarrage frontend Next.js…"
    if [ -f "$FRONTEND_PID" ] && kill -0 "$(cat "$FRONTEND_PID")" 2>/dev/null; then
        echo "  Frontend déjà en cours (PID $(cat "$FRONTEND_PID"))."
        return
    fi

    if ! command -v npm &>/dev/null; then
        echo "✗ npm introuvable. Installe Node.js via Homebrew : brew install node@20"
        exit 1
    fi

    cd "$FRONTEND_DIR"
    nohup npm run dev >> "$FRONTEND_LOG" 2>&1 &
    echo $! > "$FRONTEND_PID"
    echo "  Frontend démarré (PID $!, log: $FRONTEND_LOG)"
}

stop_service() {
    local name=$1 pidfile=$2
    if [ -f "$pidfile" ]; then
        local pid
        pid=$(cat "$pidfile")
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid"
            echo "  $name arrêté (PID $pid)."
        else
            echo "  $name n'était pas en cours."
        fi
        rm -f "$pidfile"
    else
        echo "  $name : aucun PID enregistré."
    fi
}

cmd="${1:-start}"

case "$cmd" in
    start)
        echo "═══ ELY — Démarrage ══════════════════════════════"
        start_qdrant
        sleep 2
        start_backend
        start_frontend
        echo ""
        echo "✓ ELY est disponible sur http://localhost:3000"
        echo "  API docs : http://localhost:8000/docs"
        echo "  Logs     : ./start.sh logs"
        ;;
    stop)
        echo "═══ ELY — Arrêt ══════════════════════════════════"
        stop_service "Backend" "$BACKEND_PID"
        stop_service "Frontend" "$FRONTEND_PID"
        echo "✓ Services arrêtés."
        ;;
    restart)
        "$0" stop
        sleep 1
        "$0" start
        ;;
    status)
        echo "═══ ELY — État ═══════════════════════════════════"
        # Qdrant
        if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^qdrant$"; then
            echo "  Qdrant  : ✅ en cours"
        else
            echo "  Qdrant  : ❌ arrêté"
        fi
        # Ollama
        if curl -s http://localhost:11434/ &>/dev/null; then
            echo "  Ollama  : ✅ en cours"
        else
            echo "  Ollama  : ❌ non accessible"
        fi
        # Backend
        if [ -f "$BACKEND_PID" ] && kill -0 "$(cat "$BACKEND_PID")" 2>/dev/null; then
            echo "  Backend : ✅ en cours (PID $(cat "$BACKEND_PID"))"
        else
            echo "  Backend : ❌ arrêté"
        fi
        # Frontend
        if [ -f "$FRONTEND_PID" ] && kill -0 "$(cat "$FRONTEND_PID")" 2>/dev/null; then
            echo "  Frontend: ✅ en cours (PID $(cat "$FRONTEND_PID"))"
        else
            echo "  Frontend: ❌ arrêté"
        fi
        ;;
    logs)
        echo "═══ ELY — Logs (Ctrl+C pour quitter) ════════════"
        tail -f "$BACKEND_LOG" "$FRONTEND_LOG"
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|logs}"
        exit 1
        ;;
esac
