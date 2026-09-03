# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/memory/recall_service.py
# @brief      MemoryRecallService — unified `recall(type, query)` API over
#             the 5 typed stores.
# @license    MIT
#            https://opensource.org/licenses/MIT
# @version    1.3.0
# =============================================================================
"""Unified `memory_recall(type, query)` — Sprint 2.5 §3.

The public API of the typed memory subpackage. Every caller (LangChain
tool, voice loop, supervisor) goes through this service rather than
poking the underlying stores directly. This is the seam that lets us
change physical storage later (e.g. Qdrant→pgvector) without breaking
callers.

`type=AUTO` fans out to all relevant stores in parallel and merges
results by score. `type=ERROR` returns empty in V1 (write-only — read
path lands in Sprint 3.7).
"""
from __future__ import annotations

import asyncio
import logging
from functools import lru_cache

from app.services.memory._infra import get_memory_infra
from app.services.memory.constraint_store import ConstraintStore
from app.services.memory.episodic_store import EpisodicStore
from app.services.memory.semantic_user_store import SemanticUserStore
from app.services.memory.types import MemoryHit, MemoryType

logger = logging.getLogger(__name__)


class UnreadableMemoryType(RuntimeError):
    """Ce type de mémoire n'a aucune lecture implémentée.

    Distinct d'un « aucun résultat » : la nuance compte pour le modèle. Une
    liste vide se lit « je n'ai rien en mémoire là-dessus » — une affirmation
    sur le monde. Cette exception dit « cette mémoire n'est pas consultable »
    — une affirmation sur l'outil. Confondre les deux, c'est fabriquer une
    façade, ce que la boucle d'auto-diagnostic cherche justement à détecter.
    """

    def __init__(self, memory_type: MemoryType) -> None:
        self.memory_type = memory_type
        super().__init__(f"memory type {memory_type.value!r} is not readable")


# ERROR : écriture seule — les erreurs partent en failure_cases, rien ne les
# relit.
#
# PROCEDURAL en est SORTI (02/08, Sprint 2.5 §2.5.2) : il n'a toujours pas de
# magasin à lui, et n'en aura pas. Sa source est le registre d'outils, déjà
# interrogeable en langage naturel par `find_tool`. Le sprint demandait « le
# catalogue requêtable » et non « une table de plus » — il est donc servi
# depuis cette voie-là, pas dupliqué.
_UNREADABLE_TYPES = frozenset({MemoryType.ERROR})


class MemoryRecallService:
    """Unified entry-point for typed memory recall."""

    def __init__(self) -> None:
        infra = get_memory_infra()
        self.constraints = ConstraintStore(infra)
        self.episodic = EpisodicStore(infra)
        self.semantic = SemanticUserStore(infra)

    async def recall(
        self,
        memory_type: MemoryType | str,
        query: str,
        user_id: str,
        limit: int = 5,
        filter: dict | None = None,  # reserved for V2 — currently ignored
    ) -> list[MemoryHit]:
        """Recall memories of `memory_type` matching `query` for `user_id`.

        Best-effort sur ce qui SE LIT : une recherche infructueuse rend une
        liste vide, jamais une exception — l'appelant n'a pas à se défendre
        contre un magasin qui n'a rien trouvé.

        UNE exception, et une seule : ``UnreadableMemoryType``, levée quand
        le type demandé n'a aucune lecture derrière lui (``ERROR``). Rendre
        ``[]`` dans ce cas ferait lire au modèle « je n'ai jamais échoué
        là-dessus » — une absence de lecture présentée comme un fait
        constaté. Un appelant qui interroge un type non lisible a un bug,
        et il doit l'apprendre.
        """
        if not user_id:
            logger.warning("memory_recall refused: empty user_id")
            return []
        if not query or not query.strip():
            return []

        mt = MemoryType.parse(memory_type)
        # ERROR n'a AUCUNE lecture derrière lui (écriture seule — les erreurs
        # vont en failure_cases). Levé AVANT le try : rendre [] ferait lire au
        # modèle « je n'ai jamais échoué là-dessus » — une affirmation fausse
        # présentée comme un fait.
        if mt in _UNREADABLE_TYPES:
            raise UnreadableMemoryType(mt)
        try:
            if mt == MemoryType.AUTO:
                return await self._recall_auto(query, user_id, limit)
            if mt == MemoryType.EPISODIC:
                return await self._recall_episodic(query, user_id, limit)
            if mt == MemoryType.SEMANTIC_USER:
                return await self._recall_semantic_user(query, user_id, limit)
            if mt == MemoryType.CONSTRAINT:
                return await self._recall_constraint(query, user_id, limit)
            if mt == MemoryType.PROCEDURAL:
                return await self._recall_procedural(query, user_id, limit)
        except Exception as exc:
            logger.warning(
                "MemoryRecallService.recall(%s) failed: %s — returning []",
                mt.value, exc,
            )
            return []
        return []

    # ── Per-type recall implementations ────────────────────────────────

    async def _recall_episodic(
        self, query: str, user_id: str, limit: int
    ) -> list[MemoryHit]:
        rows = await self.episodic.get_relevant(query, user_id, limit)
        out: list[MemoryHit] = []
        for r in rows:
            content = r.get("content") or r.get("user_message") or ""
            out.append(MemoryHit(
                type=MemoryType.EPISODIC,
                content=content,
                # episodic.get_relevant doesn't currently surface the
                # hybrid score — placeholder 1.0 here is fine for V1.
                score=1.0,
                metadata={
                    "user_message": r.get("user_message"),
                    "assistant_message": r.get("assistant_message"),
                    "conversation_id": r.get("conversation_id"),
                },
                created_at=str(r.get("created_at")) if r.get("created_at") else None,
            ))
        return out

    async def _recall_semantic_user(
        self, query: str, user_id: str, limit: int
    ) -> list[MemoryHit]:
        facts, prefs = await asyncio.gather(
            self.semantic.get_relevant_facts(query, user_id, limit),
            self.semantic.get_preferences(user_id, limit),
        )
        out: list[MemoryHit] = []
        for content in facts:
            out.append(MemoryHit(
                type=MemoryType.SEMANTIC_USER,
                content=content,
                score=1.0,
                metadata={"kind": "fact"},
            ))
        for content in prefs:
            out.append(MemoryHit(
                type=MemoryType.SEMANTIC_USER,
                content=content,
                score=1.0,
                metadata={"kind": "preference"},
            ))
        return out[:limit]

    async def _recall_constraint(
        self, query: str, user_id: str, limit: int
    ) -> list[MemoryHit]:
        rules = await self.constraints.get_relevant(query, user_id, limit)
        return [
            MemoryHit(
                type=MemoryType.CONSTRAINT,
                content=rule,
                score=1.0,
                metadata={"priority": "high"},
            )
            for rule in rules
        ]

    async def _recall_procedural(
        self, query: str, user_id: str, limit: int
    ) -> list[MemoryHit]:
        """Le catalogue d'outils, requêtable en langage naturel — §2.5.2.

        Pas de magasin : la source est le registre, et le classement est celui
        de ``find_tool``. Ajouter un outil au code le rend donc visible ici
        sans autre geste — c'est le livrable mesurable que le sprint demandait.

        Import LOCAL, pas en tête de module : ``find_tool_skill`` importe déjà
        ``app.services.memory`` pour l'encodeur fastembed, un import de module
        refermerait le cycle. Le dépôt fait pareil ailleurs (``_search_hybrid``
        importe ``fts_store`` dans le corps).

        ``user_id`` n'est pas utilisé : le catalogue est le même pour tous. Les
        outils APPRIS, eux, sont personnels — mais ils ne sont pas dans ce
        registre, et c'est ``find_tool`` qui les couvre.
        """
        from app.skills.builtin.find_tool_skill import rank_tools_for_capability

        pairs = await rank_tools_for_capability(query, limit)
        return [
            MemoryHit(
                type=MemoryType.PROCEDURAL,
                content=f"{name} — {summary}" if summary else name,
                score=1.0,
                metadata={"tool_name": name},
            )
            for name, summary in pairs
        ]

    # ── Fan-out (AUTO) ─────────────────────────────────────────────────

    async def _recall_auto(
        self, query: str, user_id: str, limit: int
    ) -> list[MemoryHit]:
        """Parallel fan-out to all reading stores, merged & sorted by score.

        ERROR and PROCEDURAL are both skipped. Each store gets `limit` slots
        in its own search, then we keep the top `limit` across the merged
        pool. Constraints are de-prioritised slightly so semantic/episodic
        hits surface first when both score equally (constraints are
        injected separately into the system prompt).
        """
        # PROCEDURAL hors du fan-out, délibérément (02/08) : « de quoi te
        # souviens-tu à propos de X » ne doit pas rendre des noms d'outils au
        # milieu des souvenirs. La procédurale répond à une AUTRE question —
        # « par quel moyen fait-on X » — et se demande explicitement.
        # L'ajouter ici casse test_recall_auto_fans_out_to_all_stores_and_merges,
        # qui épingle exactement les trois familles ci-dessous.
        results = await asyncio.gather(
            self._recall_episodic(query, user_id, limit),
            self._recall_semantic_user(query, user_id, limit),
            self._recall_constraint(query, user_id, limit),
            return_exceptions=True,
        )
        merged: list[MemoryHit] = []
        for r in results:
            if isinstance(r, Exception):
                logger.warning("recall_auto fan-out branch failed: %s", r)
                continue
            merged.extend(r)
        merged.sort(key=lambda h: h.score, reverse=True)
        return merged[:limit]


@lru_cache(maxsize=1)
def get_memory_recall_service() -> MemoryRecallService:
    return MemoryRecallService()
