# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/scripts/bench_pii_ner.py
# @brief      Bench GLiNER (urchade/gliner_multi_pii-v1) pour la couche 2 NER
#             du SecurityFilter — latence, RAM résidente, qualité FR.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#
# Usage (venv dédié, PAS le .venv backend — gliner tire torch) :
#   uv venv /tmp/gliner_bench_venv --python 3.12
#   uv pip install --python /tmp/gliner_bench_venv/bin/python gliner psutil
#   /tmp/gliner_bench_venv/bin/python backend/scripts/bench_pii_ner.py
#
# Mesure :
#   1. RAM résidente (RSS) avant/après chargement modèle + après inférences
#   2. Latence par message sur textes FR de 50 à 2000 caractères (CPU,
#      car la prod tourne dans Docker sur le Mac → pas de MPS)
#   3. Qualité sur corpus FR réaliste : noms, organisations, adresses,
#      avec pièges (« pierre » nom commun, marques, etc.) à 3 seuils
#   4. Simulation du chemin chaud chat.py : 40 messages d'historique
#      ré-anonymisés à chaque tour, cache par hash de message
# =============================================================================
import hashlib
import json
import statistics
import sys
import time

import psutil

# Labels zero-shot ciblés : on ne ferme QUE le trou documenté (noms, orgs,
# adresses en texte libre). email/téléphone/IBAN/CB restent à la couche 1
# regex (déterministe, jamais de faux négatif sur les formats connus).
LABELS = ["person", "organization", "address"]

MB = 1024 * 1024


def rss_mb() -> float:
    return psutil.Process().memory_info().rss / MB


# ── Corpus latence : textes FR réalistes, calibrés en longueur ──────────────
_SENTENCE_POOL = (
    "Bonjour, peux-tu vérifier mon agenda de demain et me dire si la réunion "
    "avec l'équipe commerciale est confirmée ? Ensuite il faudra préparer le "
    "compte rendu de la visite chez le client et l'envoyer avant vendredi. "
    "Le dossier de candidature doit être déposé à la mairie avant la fin du "
    "mois, pense à joindre le justificatif de domicile et la pièce d'identité. "
    "La livraison du matériel est prévue mardi matin entre neuf heures et "
    "midi, quelqu'un doit être présent pour signer le bon de réception. "
    "Concernant la facture du mois dernier, le montant ne correspond pas au "
    "devis initial, il faudrait demander un avoir ou une explication. "
)


def _latency_text(length: int) -> str:
    base = "Jean-Marc Castaing de la société Sopra Steria habite au 14 rue des Lilas à Toulouse. "
    txt = base + _SENTENCE_POOL * (length // len(_SENTENCE_POOL) + 1)
    return txt[:length]


LATENCY_LENGTHS = [50, 200, 500, 1000, 2000]

# ── Corpus qualité : (texte, doit_détecter, ne_doit_PAS_détecter) ───────────
# doit_détecter : sous-chaînes qui doivent apparaître dans AU MOINS une
#   entité détectée (label indifférent parmi LABELS — un nom tagué
#   "organization" reste anonymisé, c'est ce qui compte pour la PII).
# ne_doit_PAS : sous-chaînes qui ne doivent être couvertes par AUCUNE entité.
QUALITY_CORPUS = [
    # Noms + organisations simples
    ("Bonjour, je m'appelle Jean Dupont et je travaille chez Capgemini à Lyon.",
     ["Jean Dupont", "Capgemini"], []),
    ("Profil intéressant : Sophie Lefebvre, directrice marketing chez Decathlon à Bordeaux.",
     ["Sophie Lefebvre", "Decathlon"], []),
    ("Notre client BNP Paribas souhaite une démo la semaine prochaine.",
     ["BNP Paribas"], []),
    ("Réunion avec M. Bernard de la société TotalEnergies jeudi à 14h.",
     ["Bernard", "TotalEnergies"], []),
    ("Va chercher Marion à la gare, son train arrive à 18h12.",
     ["Marion"], []),
    # Adresses
    ("Pouvez-vous envoyer le contrat à Mme Claire Moreau, 12 rue de la République, 69002 Lyon ?",
     ["Claire Moreau", "12 rue de la République"], []),
    ("Adresse de livraison : 87 boulevard Saint-Germain, 75006 Paris.",
     ["87 boulevard Saint-Germain"], []),
    ("Le siège est situé 4 avenue des Champs-Élysées, 75008 Paris, au 3e étage.",
     ["4 avenue des Champs-Élysées"], []),
    # Pièges : « pierre » nom commun vs prénom
    ("Il a posé une pierre sur le muret avant de partir.",
     [], ["pierre"]),
    ("Le maçon a monté un mur en pierre de taille la semaine dernière.",
     [], ["pierre"]),
    ("Pierre m'a appelé hier soir pour le devis de la terrasse.",
     ["Pierre"], []),
    # Pièges : marques homonymes de noms communs
    ("J'ai souscrit un abonnement fibre chez Orange et un forfait mobile chez Free.",
     ["Orange", "Free"], []),
    ("Elle a acheté une orange et une pomme au marché ce matin.",
     [], ["orange", "pomme"]),
    ("Il fait carrefour entre deux rues, attention en traversant.",
     [], ["carrefour"]),
    ("Les courses ont été livrées par Carrefour hier soir.",
     ["Carrefour"], []),
    # Noms communs capitalisés en début de phrase (piège classique NER)
    ("Mercredi prochain nous irons au cinéma avec les enfants.",
     [], ["Mercredi"]),
    ("Merci pour ton retour rapide sur le document partagé.",
     [], ["Merci"]),
    # Mix avec PII couverte par la couche 1 (recouvrement regex/NER)
    ("Contactez Julien Petit au 06 12 34 56 78 ou julien.petit@gmail.com pour le devis.",
     ["Julien Petit"], []),
    # Prospection LinkedIn réaliste (cas d'usage mission)
    ("J'ai identifié trois prospects : Awa Diallo (DRH, Veolia), Marc-Antoine "
     "Lebrun (CTO, Doctolib) et Inès Garcia, fondatrice de la startup Alan.",
     ["Awa Diallo", "Veolia", "Marc-Antoine Lebrun", "Doctolib", "Inès Garcia", "Alan"], []),
    # Texte neutre — zéro entité attendue
    ("Quelle heure est-il ? Peux-tu me rappeler la météo de demain matin ?",
     [], []),
    ("La réunion d'équipe est reportée à la semaine prochaine en visio.",
     [], []),
    # Nom dans une phrase longue avec contexte administratif
    ("Suite à votre appel, le dossier de Madame Fatou N'Diaye a été transmis "
     "au service compétent de la préfecture de Seine-Saint-Denis.",
     ["Fatou N'Diaye"], []),
]


def _spans_cover(text: str, needle: str, entities: list[dict]) -> bool:
    """True si AU MoINS une entité détectée couvre une occurrence de needle."""
    idx = text.find(needle)
    while idx != -1:
        for e in entities:
            if e["start"] <= idx and e["end"] >= idx + len(needle):
                return True
        idx = text.find(needle, idx + 1)
    return False


def _spans_touch(text: str, needle: str, entities: list[dict]) -> bool:
    """True si une entité détectée chevauche une occurrence de needle
    (insensible à la casse — utilisé pour les ne_doit_PAS)."""
    low = text.lower()
    nlow = needle.lower()
    idx = low.find(nlow)
    while idx != -1:
        for e in entities:
            if e["start"] < idx + len(needle) and e["end"] > idx:
                return True
        idx = low.find(nlow, idx + 1)
    return False


def main() -> None:
    print(f"Python {sys.version.split()[0]}, psutil {psutil.__version__}")
    rss_before = rss_mb()
    print(f"RSS avant import torch/gliner : {rss_before:.0f} Mo")

    t0 = time.perf_counter()
    import torch  # noqa: F401  (mesure d'empreinte import)
    from gliner import GLiNER
    t_import = time.perf_counter() - t0
    rss_imports = rss_mb()
    print(f"RSS après imports : {rss_imports:.0f} Mo (+{rss_imports - rss_before:.0f}) — {t_import:.1f}s")

    t0 = time.perf_counter()
    model = GLiNER.from_pretrained("urchade/gliner_multi_pii-v1")
    model.eval()
    t_load = time.perf_counter() - t0
    rss_loaded = rss_mb()
    print(f"RSS après chargement modèle : {rss_loaded:.0f} Mo (+{rss_loaded - rss_imports:.0f}) — load {t_load:.1f}s")

    # Warmup (compilation des kernels, allocations lazy)
    for _ in range(3):
        model.predict_entities(_latency_text(500), LABELS, threshold=0.5)

    # ── 1. Latence par longueur de texte (CPU) ──────────────────────────────
    print("\n── Latence par message (CPU, threshold=0.5) ──")
    results: dict[int, dict[str, float]] = {}
    for length in LATENCY_LENGTHS:
        text = _latency_text(length)
        times = []
        for _ in range(10):
            t0 = time.perf_counter()
            model.predict_entities(text, LABELS, threshold=0.5)
            times.append((time.perf_counter() - t0) * 1000)
        results[length] = {
            "mean_ms": statistics.mean(times),
            "median_ms": statistics.median(times),
            "p95_ms": sorted(times)[8],  # 9e/10 ≈ p90-95
        }
        r = results[length]
        print(f"  {length:>5} chars : mean {r['mean_ms']:7.1f} ms | median {r['median_ms']:7.1f} ms | p95 {r['p95_ms']:7.1f} ms")

    rss_after_inference = rss_mb()
    print(f"\nRSS après inférences : {rss_after_inference:.0f} Mo")

    # ── 2. Qualité sur corpus FR (3 seuils) ─────────────────────────────────
    print("\n── Qualité corpus FR ──")
    for threshold in (0.3, 0.5, 0.7):
        tp = fn = fp = 0
        misses: list[str] = []
        falses: list[str] = []
        for text, must, must_not in QUALITY_CORPUS:
            ents = model.predict_entities(text, LABELS, threshold=threshold)
            for needle in must:
                if _spans_cover(text, needle, ents):
                    tp += 1
                else:
                    fn += 1
                    misses.append(f"{needle!r} dans {text[:60]!r}")
            for needle in must_not:
                if _spans_touch(text, needle, ents):
                    fp += 1
                    falses.append(f"{needle!r} dans {text[:60]!r}")
        total_must = tp + fn
        recall = tp / total_must if total_must else 1.0
        print(f"  threshold={threshold} : rappel {tp}/{total_must} ({recall:.0%}), faux positifs pièges {fp}")
        if misses:
            for m in misses:
                print(f"      MISS {m}")
        if falses:
            for f_ in falses:
                print(f"      FAUX+ {f_}")

    # ── 3. Simulation chemin chaud chat.py : 40 messages, cache par hash ────
    # Tour N : 38-40 messages déjà vus (cache hit) + 1-2 nouveaux (miss).
    print("\n── Simulation chemin chaud (40 messages historique, cache hash→spans) ──")
    history = [_latency_text(150 + i * 37) for i in range(40)]
    cache: dict[str, list] = {}

    def anonymize_with_cache(text: str) -> float:
        t0 = time.perf_counter()
        key = hashlib.sha256(text.encode()).hexdigest()
        if key not in cache:
            cache[key] = model.predict_entities(text, LABELS, threshold=0.5)
        _ = cache[key]
        return (time.perf_counter() - t0) * 1000

    # Tour 1 : cache froid (40 miss) — pire cas (1re requête d'une conv longue)
    cold = [anonymize_with_cache(m) for m in history]
    # Tour 2 : cache chaud + 2 nouveaux messages (le cas nominal)
    history.append(_latency_text(777))
    history.append(_latency_text(1234))
    warm = [anonymize_with_cache(m) for m in history]
    print(f"  Tour 1 (cache froid, 40 miss)  : total {sum(cold):8.1f} ms | moyenne {statistics.mean(cold):6.1f} ms/msg")
    print(f"  Tour 2 (38 hit + 2 miss)       : total {sum(warm):8.1f} ms | moyenne {statistics.mean(warm):6.1f} ms/msg")
    hits = [t for t in warm if t < 1.0]
    print(f"  Coût d'un cache hit            : {statistics.mean(hits) * 1000:.0f} µs ({len(hits)} hits)")

    rss_final = rss_mb()
    print(f"\nRSS final : {rss_final:.0f} Mo (empreinte modèle+runtime ≈ {rss_final - rss_before:.0f} Mo au-dessus du process nu)")

    # Verdict machine-readable pour la design note
    print("\n" + json.dumps({
        "rss_model_mb": round(rss_final - rss_before),
        "latency_mean_ms": {str(k): round(v["mean_ms"], 1) for k, v in results.items()},
        "warm_turn_mean_ms_per_msg": round(statistics.mean(warm), 2),
    }))


if __name__ == "__main__":
    main()
