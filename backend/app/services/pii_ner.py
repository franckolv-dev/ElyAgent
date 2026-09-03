# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/pii_ner.py
# @brief      Couche 2 NER du SecurityFilter — GLiNER (urchade/gliner_multi_pii-v1)
#             en ONNX int8, derrière le flag PII_NER_ENABLED (défaut OFF).
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @version    1.0.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""Moteur NER zero-shot pour la couche 2 du SecurityFilter.

Design cadré par le bench du 2026-06-10 (``scripts/bench_pii_ner.py``,
M1 Max, CPU) :

- **Périmètre** : UNIQUEMENT ``person`` / ``organization`` / ``address``.
  email / téléphone / IBAN / CB restent à la couche 1 regex (déterministe)
  — ce qui élimine la classe de faux positifs « le mot "mail" détecté
  comme email (0.71) » observée au bench.
- **Seuil 0.5** : meilleur compromis rappel/faux positifs mesuré.
- **ONNX int8 OBLIGATOIRE** : le modèle PyTorch fp32 pèse 2553 Mo de RSS
  — inacceptable dans le conteneur backend cappé à 4g. La quantization
  int8 vise ~500-800 Mo. Le répertoire modèle est produit OFFLINE par
  ``scripts/export_gliner_onnx.py`` (voir son en-tête) et monté via le
  volume ``./data/pii_ner`` → ``PII_NER_MODEL_DIR``.
- **Cache hash→valeurs OBLIGATOIRE** : le chemin chaud (routers/chat.py)
  ré-anonymise ~40 messages d'historique à chaque tour. Sans cache :
  +3 à 8 s/tour (~68-196 ms/message au bench). Avec : seuls les messages
  jamais vus paient l'inférence ; un hit coûte des µs.
- **Fail-open** : flag posé mais modèle/package indisponible → la couche 2
  est désactivée avec un warning au boot, la couche 1 regex reste intacte
  (= comportement de prod d'aujourd'hui). Même philosophie best-effort
  que le routing souveraineté #59.

Le chargement n'a lieu QU'AU BOOT (``load_ner_engine()`` appelé depuis le
lifespan de main.py si le flag est posé) — jamais de chargement paresseux
sur le chemin de requête. ``predict_entities`` est bloquant (~68-70 ms par
message court) : avec le cache, le cas nominal d'un tour de chat est de
0 à 2 inférences ; le pire cas (premier tour d'une longue conversation
après redémarrage du process) paie une fois puis est caché.

Les textes longs sont découpés en fenêtres de ``_CHUNK_CHARS`` caractères
(le modèle tronque silencieusement au-delà de ``max_len`` tokens — sans
découpage, les entités au-delà de ~2000 caractères ne seraient jamais
vues) et la couverture NER est plafonnée à ``PII_NER_MAX_CHARS`` pour
borner la latence sur les gros résultats d'outils. Au-delà du plafond,
la couche 1 regex couvre toujours l'intégralité du texte.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import time

from app.services.bounded_cache import BoundedLRUDict

logger = logging.getLogger(__name__)

# Labels zero-shot soumis à GLiNER (en anglais — le modèle est entraîné
# avec des labels EN, la détection sur texte FR est excellente au bench).
NER_LABELS: list[str] = ["person", "organization", "address"]

# label GLiNER → label de placeholder du SecurityFilter ([PERSON_0], …)
LABEL_TO_PLACEHOLDER: dict[str, str] = {
    "person": "PERSON",
    "organization": "ORG",
    "address": "ADDRESS",
}

# Labels de placeholder gérés par la couche 2 (utilisés par security_filter
# pour le remplacement vault-first : seules ces entrées du vault sont
# recherchées en texte libre — les valeurs EMAIL/PHONE/… sont re-détectées
# par les regex de la couche 1, déterministes).
NER_PLACEHOLDER_LABELS: frozenset[str] = frozenset(LABEL_TO_PLACEHOLDER.values())

# Seuil de confiance — validé au bench (rappel excellent, faux positifs
# limités au cas « Pierre qui roule » documenté comme acceptable car le
# placeholder est réversible).
_THRESHOLD = 0.5

# Découpage des textes longs : ~1200 chars ≈ 200 mots FR, confortablement
# sous le max_len du modèle (le point de mesure du bench : 196 ms à 1200).
_CHUNK_CHARS = 1200

# Garde-fou valeurs : une « entité » d'1 caractère est du bruit, pas une PII.
_MIN_VALUE_LEN = 2

# ── Allow-list de services (retour terrain 2026-06-11) ─────────────────────
# Les noms des plateformes qu'Ely intègre ne sont PAS de la PII : les masquer
# casse le fonctionnement même de l'agent (« vérifie mon dépôt GitHub » →
# [ORG_0] → le LLM ne sait plus quel outil appeler). Extensible sans rebuild
# via PII_NER_ALLOWLIST="nom1,nom2" (+ redémarrage). Match EXACT sur la
# valeur normalisée (minuscules, accents retirés) — pas de sous-chaîne :
# « GitHub SARL » (une vraie société cliente) resterait masqué.
_DEFAULT_SERVICE_ALLOWLIST: tuple[str, ...] = (
    "github", "google", "gmail", "google drive", "google calendar",
    "google one", "google play", "youtube", "telegram", "slack", "discord",
    "whatsapp", "linkedin", "doctolib", "ely", "claude", "anthropic",
    "deepseek", "mistral", "gemini", "openai", "ollama", "lm studio",
    "docker", "hugging face", "qdrant",
)

_allowlist_cache: tuple[str, frozenset[str]] | None = None

# ── Adresses : seul le niveau RUE est de la PII (retour terrain 11 juin) ───
# « Quelle météo à Vendeuvre-du-Poitou, Vienne, France » → [ADDRESS_1] →
# l'agent ne sait plus OÙ chercher. Une ville/région/pays est de la
# géographie publique, pas une donnée personnelle ; ce qui identifie
# quelqu'un, c'est la rue (le cas validé au bench : « 12 rue de la
# République, 33000 Bordeaux »). On ne masque une détection ADDRESS que si
# elle contient un mot de voirie ou un code postal à 5 chiffres.
_STREET_WORDS = (
    r"rue|avenue|av\.|bd\.?|boulevard|chemin|impasse|all[ée]e|place|route|"
    r"quai|cours|square|faubourg|villa|hameau|lotissement|r[ée]sidence|"
    r"chauss[ée]e|sentier|passage|esplanade"
)
_STREET_RE = re.compile(rf"\b(?:{_STREET_WORDS})\b", re.IGNORECASE)
_POSTAL_CODE_RE = re.compile(r"\b\d{5}\b")


def is_street_level_address(value: str) -> bool:
    """True si la détection ADDRESS contient un marqueur de niveau rue
    (mot de voirie ou code postal) — le seul niveau qui justifie le
    masquage. Ville / région / pays seuls restent en clair."""
    v = value or ""
    return bool(_STREET_RE.search(v) or _POSTAL_CODE_RE.search(v))


def should_mask_entity(value: str, label: str) -> bool:
    """Verdict unique de la couche 2 pour une détection (valeur, label
    placeholder) — partagé par le moteur ET SecurityFilter (défense en
    profondeur) : allow-list des services, et adresses au niveau rue
    uniquement."""
    if is_service_allowlisted(value):
        return False
    if label == "ADDRESS" and not is_street_level_address(value):
        return False
    return True


def _norm_value(s: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", (s or "").strip().lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def is_service_allowlisted(value: str) -> bool:
    """True si ``value`` est un nom de service que la couche 2 ne doit
    JAMAIS masquer (défauts + env ``PII_NER_ALLOWLIST``, cache par valeur
    d'env)."""
    global _allowlist_cache
    env = os.environ.get("PII_NER_ALLOWLIST", "")
    if _allowlist_cache is None or _allowlist_cache[0] != env:
        extra = (x for x in env.split(",") if x.strip())
        _allowlist_cache = (env, frozenset(
            _norm_value(x) for x in (*_DEFAULT_SERVICE_ALLOWLIST, *extra)
        ))
    return _norm_value(value) in _allowlist_cache[1]


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


def pii_ner_enabled() -> bool:
    """Flag global de la couche 2 — défaut OFF (zéro changement de
    comportement tant qu'il n'est pas posé explicitement)."""
    return _truthy(os.environ.get("PII_NER_ENABLED"))


def _model_dir() -> str:
    return os.environ.get(
        "PII_NER_MODEL_DIR", "/app/.cache/pii_ner/gliner_multi_pii-v1-onnx"
    )


def _max_ner_chars() -> int:
    """Plafond de couverture NER par texte (latence bornée sur les gros
    résultats d'outils : ~160 ms / 1000 chars au bench)."""
    try:
        return int(os.environ.get("PII_NER_MAX_CHARS", "8000"))
    except ValueError:
        return 8000


class PIINEREngine:
    """Enveloppe du modèle GLiNER ONNX : extraction (valeur, label) avec
    cache par hash de texte.

    Le cache stocke des PAIRES (valeur, label) et non des positions : le
    remplacement est fait par recherche directe dans security_filter (même
    mécanisme que le vault-first), donc un même texte d'historique re-soumis
    à chaque tour est un hit quel que soit l'état du vault de la
    conversation. Les valeurs en cache sont de la PII en mémoire process —
    même statut que le vault du SecurityFilter, jamais persisté.
    """

    def __init__(self, model, cache_maxsize: int = 4096) -> None:
        self._model = model
        # TTL 24 h aligné sur le registre des SecurityFilter (B-7) — un
        # texte d'historique actif est re-touché à chaque tour.
        self._cache: BoundedLRUDict = BoundedLRUDict(
            maxsize=cache_maxsize, ttl_seconds=24 * 3600,
        )

    # ------------------------------------------------------------------ #
    # API                                                                  #
    # ------------------------------------------------------------------ #

    def extract(self, text: str) -> list[tuple[str, str]]:
        """Retourne les entités du texte sous forme ``[(valeur, label)]``
        avec ``label`` ∈ {PERSON, ORG, ADDRESS}. Déduplique par valeur.

        Cache par sha256 du texte : la 2e extraction du même texte ne fait
        AUCUN appel au modèle (pin de test dédié).
        """
        if not text or not text.strip():
            return []
        key = hashlib.sha256(text.encode("utf-8")).hexdigest()
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        result = self._extract_uncached(text)
        self._cache[key] = result
        return result

    # ------------------------------------------------------------------ #
    # Interne                                                              #
    # ------------------------------------------------------------------ #

    def _extract_uncached(self, text: str) -> list[tuple[str, str]]:
        capped = text[: _max_ner_chars()]
        if len(capped) < len(text):
            logger.debug(
                "PII NER coverage capped at %d chars (text %d) — regex layer 1 "
                "still covers the full text.", len(capped), len(text),
            )
        seen: dict[str, str] = {}
        t0 = time.perf_counter()
        for chunk in self._chunks(capped):
            for ent in self._model.predict_entities(chunk, NER_LABELS, threshold=_THRESHOLD):
                value = (ent.get("text") or "").strip()
                label = LABEL_TO_PLACEHOLDER.get(ent.get("label", ""))
                if label is None or len(value) < _MIN_VALUE_LEN:
                    continue
                # Jamais de placeholder existant comme « entité » (le texte
                # post-couche-1 contient des [EMAIL_0], etc.).
                if value.startswith("[") and value.endswith("]"):
                    continue
                # Verdict partagé : allow-list services + adresses au
                # niveau rue uniquement (retours terrain 2026-06-11).
                if not should_mask_entity(value, label):
                    continue
                seen.setdefault(value, label)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        if elapsed_ms > 500:
            logger.info("PII NER slow extract: %.0f ms for %d chars (%d entities)",
                        elapsed_ms, len(capped), len(seen))
        return list(seen.items())

    @staticmethod
    def _chunks(text: str) -> list[str]:
        """Fenêtres ≤ _CHUNK_CHARS coupées sur un espace quand c'est
        possible — couper au milieu d'un nom ferait rater l'entité."""
        if len(text) <= _CHUNK_CHARS:
            return [text]
        chunks: list[str] = []
        start = 0
        while start < len(text):
            end = min(start + _CHUNK_CHARS, len(text))
            if end < len(text):
                space = text.rfind(" ", start + _CHUNK_CHARS // 2, end)
                if space != -1:
                    end = space
            chunks.append(text[start:end])
            start = end
        return chunks


# ─────────────────────────────────────────────────────────────────────────
# Singleton process — chargé au boot uniquement (lifespan main.py)
# ─────────────────────────────────────────────────────────────────────────

_engine: PIINEREngine | None = None


def get_ner_engine() -> PIINEREngine | None:
    """Moteur chargé au boot, ou ``None`` (flag off / chargement échoué).
    Ne déclenche JAMAIS de chargement — fail-open par construction."""
    return _engine


def load_ner_engine() -> bool:
    """Charge le modèle GLiNER ONNX int8 depuis ``PII_NER_MODEL_DIR``.

    Appelé une seule fois depuis le lifespan (via ``asyncio.to_thread`` —
    le chargement est du CPU bloquant). Retourne True si la couche 2 est
    opérationnelle. Tous les échecs sont fail-open : warning explicite,
    la couche 1 regex reste le comportement de prod.
    """
    global _engine
    if _engine is not None:
        return True
    if not pii_ner_enabled():
        return False

    model_dir = _model_dir()
    quantized = os.path.join(model_dir, "model_quantized.onnx")
    plain = os.path.join(model_dir, "model.onnx")
    if os.path.exists(quantized):
        onnx_file = "model_quantized.onnx"
    elif os.path.exists(plain):
        # fp32 ONNX ≈ 1.1 Go de RSS — tolérée mais hors cible mémoire.
        logger.warning(
            "PII NER: model_quantized.onnx absent de %s — chargement du "
            "model.onnx fp32 (RAM hors cible ; relancer "
            "scripts/export_gliner_onnx.py avec la quantization).", model_dir,
        )
        onnx_file = "model.onnx"
    else:
        logger.error(
            "PII_NER_ENABLED est posé mais aucun modèle ONNX dans %s. "
            "Exporter d'abord le modèle : voir scripts/export_gliner_onnx.py "
            "(host, venv dédié) puis redémarrer. Couche 2 désactivée — "
            "la couche 1 regex reste active.", model_dir,
        )
        return False

    try:
        from gliner import GLiNER  # import lourd (tire torch) — boot only
    except ImportError:
        logger.error(
            "PII_NER_ENABLED est posé mais le package `gliner` n'est pas "
            "installé. Rebuild avec PII_NER_INSTALL=1 (docker compose build "
            "--build-arg PII_NER_INSTALL=1, voir backend/Dockerfile). "
            "Couche 2 désactivée — la couche 1 regex reste active.",
        )
        return False

    t0 = time.perf_counter()
    model = GLiNER.from_pretrained(
        model_dir,
        load_onnx_model=True,
        onnx_model_file=onnx_file,
        local_files_only=True,
        map_location="cpu",
    )
    # Warmup : la 1re inférence paie les allocations lazy d'onnxruntime —
    # autant le faire au boot qu'au premier message d'un utilisateur.
    model.predict_entities(
        "Jean-Marc Castaing de la société Sopra Steria habite au 14 rue des Lilas à Toulouse.",
        NER_LABELS, threshold=_THRESHOLD,
    )
    _engine = PIINEREngine(model)
    logger.info(
        "PII NER layer 2 ready: %s/%s loaded in %.1fs (labels=%s, threshold=%.1f)",
        model_dir, onnx_file, time.perf_counter() - t0, NER_LABELS, _THRESHOLD,
    )
    return True


def unload_ner_engine() -> None:
    """Décharge le moteur (tests)."""
    global _engine
    _engine = None
