# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/scripts/probe_tier_a_models.py
# @brief      Probes comparatives de modèles candidats au tiers A — latence
#             perçue + correction sur 5 questions représentatives du tiers.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#
# Le tiers A = réponses one-shot SANS toolset bindé, face à l'utilisateur :
# le critère est « le plus VIF qui soit correct » (le raisonnement s'achète
# au routeur, pas au tiers rapide — leçon LFM2.5, 2026-06-12). Ce script
# compare N modèles chargés dans LM Studio sur 5 probes tier-A-style et
# mesure ce que l'utilisateur ressent : temps au PREMIER token et temps
# total, plus des vérifications de correction basiques.
#
# Usage (host, aucun venv requis — stdlib seulement) :
#   python3 backend/scripts/probe_tier_a_models.py gemma-4-e4b-it-mlx lfm2.5-8b-a1b-mlx
#   python3 backend/scripts/probe_tier_a_models.py --list   # modèles dispo
# =============================================================================
from __future__ import annotations

import json
import sys
import time
import urllib.request

BASE_URL = "http://localhost:1234/v1"

# (question, vérification de correction sur la réponse en minuscules)
PROBES: list[tuple[str, str]] = [
    ("Salut ! Tu peux me tutoyer. Comment tu t'appelles ?",
     ""),  # pure vivacité conversationnelle — pas de check de fond
    ("En une phrase : quelle est la capitale de l'Australie ?",
     "canberra"),
    ("Réponds UNIQUEMENT par le nombre, sans phrase : combien font 17 × 23 ?",
     "391"),
    ("Résume en UNE phrase : « Le projet a pris du retard car le fournisseur "
     "a livré les pièces avec trois semaines de décalage, mais l'équipe a "
     "rattrapé une semaine en parallélisant l'assemblage et les tests. »",
     ""),
    ("Traduis en anglais : « la réunion de demain est reportée à vendredi matin »",
     "friday"),
]


def list_models() -> list[str]:
    with urllib.request.urlopen(f"{BASE_URL}/models", timeout=10) as r:
        return [m["id"] for m in json.load(r)["data"]]


def probe(model: str, question: str) -> tuple[float, float, str]:
    """Retourne (premier_token_s, total_s, texte) en streaming SSE."""
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": question}],
        "temperature": 0.2,
        "max_tokens": 300,
        "stream": True,
    }).encode()
    req = urllib.request.Request(
        f"{BASE_URL}/chat/completions", data=body,
        headers={"Content-Type": "application/json"},
    )
    t0 = time.perf_counter()
    first: float | None = None
    chunks: list[str] = []
    with urllib.request.urlopen(req, timeout=300) as resp:
        for raw_line in resp:
            line = raw_line.decode("utf-8", "replace").strip()
            if not line.startswith("data: ") or line == "data: [DONE]":
                continue
            try:
                delta = json.loads(line[6:])["choices"][0]["delta"]
            except (ValueError, KeyError, IndexError):
                continue
            # Le contenu UTILE seulement — les tokens de raisonnement
            # (reasoning_content) ne comptent pas comme premier token :
            # l'utilisateur ne les voit pas, il attend.
            piece = delta.get("content") or ""
            if piece:
                if first is None:
                    first = time.perf_counter() - t0
                chunks.append(piece)
    return (first if first is not None else float("inf"),
            time.perf_counter() - t0, "".join(chunks))


def main() -> int:
    args = [a for a in sys.argv[1:] if a != "--list"]
    if "--list" in sys.argv or not args:
        print("Modèles disponibles dans LM Studio :")
        for m in list_models():
            print(" •", m)
        if not args:
            print("\nUsage : probe_tier_a_models.py <model_id> [model_id...]")
            return 0

    results: dict[str, dict] = {}
    for model in args:
        print(f"\n{'═' * 64}\n## {model}")
        firsts, totals, fails = [], [], []
        for i, (q, must) in enumerate(PROBES, 1):
            try:
                first, total, text = probe(model, q)
            except Exception as exc:
                print(f"  P{i} ERREUR : {exc}")
                fails.append(f"P{i}:erreur")
                continue
            ok = (must in text.lower()) if must else bool(text.strip())
            if not ok:
                fails.append(f"P{i}:{must or 'vide'}")
            print(f"  P{i} 1er token {first:5.2f}s | total {total:5.2f}s | "
                  f"{'✓' if ok else '✗'} {text.strip()[:60]!r}")
            firsts.append(first)
            totals.append(total)
        if firsts:
            results[model] = {
                "first_median": sorted(firsts)[len(firsts) // 2],
                "total_median": sorted(totals)[len(totals) // 2],
                "fails": fails,
            }

    if len(results) > 1:
        print(f"\n{'═' * 64}\n## Verdict (médianes)")
        for model, r in sorted(results.items(), key=lambda kv: kv[1]["first_median"]):
            print(f"  {model:<32} 1er token {r['first_median']:5.2f}s | "
                  f"total {r['total_median']:5.2f}s | "
                  f"{'échecs: ' + ', '.join(r['fails']) if r['fails'] else 'correct ✓'}")
        print("\nRègle tier A : le plus VIF dont toutes les probes sont ✓.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
