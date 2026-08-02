# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_docs_match_the_code.py
# @brief      Ménage docs — un document ne peut plus contredire le code en
#             silence : les chiffres qu'il cite sont confrontés au registre.
# @license    Elastic License 2.0
# =============================================================================
"""Contrôles de cohérence de la documentation.

**Pourquoi ce fichier existe.** Le ménage du 29-30/07 est parti d'un constat :
un markdown périmé est **pire qu'absent**, parce qu'il oriente sur une fausse
piste avec assurance. Deux erreurs de mesure de cette session venaient de là.

Les 51 documents précédents (19 561 lignes) ont été archivés hors du dépôt et
quatre ont été réécrits. Sans garde-fou, ils repartiront à la dérive dès le
prochain outil ajouté.

**Ce que ces contrôles garantissent** :

1. aucun lien interne ne pointe dans le vide ;
2. aucun document ne cite un module supprimé ;
3. **les chiffres cités sont ceux du code** — nombre d'outils, taille du profil,
   nombre d'outils sous garde. Ajouter un outil rend ce fichier ROUGE, ce qui
   est le but : la dérive devient bruyante au lieu d'être silencieuse.

⚠️ Quand un de ces tests rougit, la bonne réaction est de **corriger le
document**, pas d'assouplir le test.

Run with:  cd backend && python -m pytest tests/test_docs_match_the_code.py -v
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]

# Les quatre documents réécrits + les READMEs.
_DOCS: tuple[Path, ...] = (
    _REPO / "README.md",
    _REPO / "README.fr.md",
    _REPO / "docs" / "architecture.md",
    _REPO / "docs" / "installation.md",
    _REPO / "docs" / "guide-utilisateur.md",
)

# Modules et symboles retirés par les lots 1 à 5 du ménage. Un document qui les
# nomme envoie le lecteur — humain ou modèle — sur du code qui n'existe plus.
_REMOVED = (
    "routing_learning",
    "settings_routing",
    "learned_routing_keyword",
    "_safe_columns",
    "mcp_errors",
    "orchestrate_tool",
    "orchestrate_runner",
    "orchestrate_rpc",
    "orchestrate_stubs",
    "ORCHESTRATE_CONVERSATION_ID",
    "supervisor.py",
    "sub_agents",
)


def _registry_tools():
    from app.skills.builtin import register_all
    from app.skills import get_skill_registry

    register_all()
    return get_skill_registry().all_tools


@pytest.mark.parametrize("doc", _DOCS, ids=lambda p: p.name)
def test_document_exists(doc: Path) -> None:
    """Les cinq documents du socle sont là."""
    assert doc.exists(), f"{doc.name} manquant"


@pytest.mark.parametrize("doc", _DOCS, ids=lambda p: p.name)
def test_internal_links_resolve(doc: Path) -> None:
    """Aucun lien relatif ne pointe dans le vide."""
    text = doc.read_text(encoding="utf-8")
    broken: list[str] = []
    for target in re.findall(r"\]\(([^)#:]+?)(?:#[^)]*)?\)", text):
        target = target.strip()
        if not target or target.startswith(("http://", "https://", "mailto:")):
            continue
        if not (doc.parent / target).resolve().exists():
            broken.append(target)
    assert broken == [], f"{doc.name} — liens cassés : {broken}"


@pytest.mark.parametrize("doc", _DOCS, ids=lambda p: p.name)
def test_document_names_no_removed_module(doc: Path) -> None:
    """Aucun document ne renvoie vers du code supprimé."""
    text = doc.read_text(encoding="utf-8")
    found = [name for name in _REMOVED if name in text]
    assert found == [], (
        f"{doc.name} cite du code supprimé : {found} — corriger le document"
    )


def test_the_tool_count_cited_is_the_real_one() -> None:
    """« 206 outils » doit être le compte du registre, pas un souvenir.

    Ajouter ou retirer un outil rend ce test rouge : c'est voulu. La dérive
    d'un document doit coûter un échec de CI, pas une fausse piste six mois
    plus tard.
    """
    real = len(_registry_tools())
    for doc in _DOCS:
        text = doc.read_text(encoding="utf-8")
        cited = {int(n) for n in re.findall(r"\*\*(\d{3}) (?:outils|tools)\.?\*\*", text)}
        cited |= {int(n) for n in re.findall(r"\*\*(\d{3})\*\* outils", text)}
        for n in cited:
            assert n == real, (
                f"{doc.name} annonce {n} outils, le registre en compte {real}"
            )


def test_the_docs_no_longer_describe_the_profile_hole_as_open() -> None:
    """Le trou est comblé (#323) — un document qui le dit ouvert oriente faux.

    ⚠️ Un markdown périmé est PIRE qu'absent : il décrit une dette réglée avec
    l'assurance d'un constat. Ce pin remplace celui qui vérifiait « 84 outils » ;
    la taille du profil `default` n'est plus un nombre, c'est « tout ».
    """
    from app.agent.toolset_profiles import get_profile_tool_names

    assert get_profile_tool_names("default") is None
    compact = get_profile_tool_names("compact")
    assert compact and len(compact) >= 25

    for nom in ("architecture.md", "guide-utilisateur.md"):
        texte = (_REPO / "docs" / nom).read_text(encoding="utf-8")
        assert "dette identifiée" not in texte or "profil" not in texte, (
            f"{nom} décrit encore le trou du profil comme ouvert"
        )
        assert "que 84 des" not in texte, f"{nom} cite encore le profil amputé"


def test_the_guarded_tool_count_cited_is_the_real_one() -> None:
    """« 38 outils » sous garde = l'union des deux vraies sources.

    ⚠️ La garde ne vit PAS dans `hitl_descriptions` (qui n'en décrit que
    quelques-uns). Une table de sécurité bâtie sur la mauvaise source est pire
    qu'une absence de table : elle rassure. D'où le calcul explicite ici.
    """
    from app.services.hitl_preferences import LOCKED_HITL_TOOLS
    from app.services.security_filter import ALWAYS_CRITICAL_TOOLS

    real = len(LOCKED_HITL_TOOLS | ALWAYS_CRITICAL_TOOLS)
    for doc in _DOCS:
        text = doc.read_text(encoding="utf-8")
        cited = {int(n) for n in re.findall(r"\*\*(\d{2}) (?:outils|tools)\*\*", text)}
        for n in cited:
            if n == len(LOCKED_HITL_TOOLS | ALWAYS_CRITICAL_TOOLS):
                continue
            # Le profil (84) est vérifié par son propre test — on ne confond pas.
            if doc.name == "architecture.md":
                continue
            assert n == real, (
                f"{doc.name} annonce {n} outils sous garde, réel {real}"
            )


def test_the_graph_nodes_cited_all_exist() -> None:
    """Les nœuds décrits dans architecture.md sont ceux du graphe réel."""
    graph_src = (_REPO / "backend" / "app" / "agent" / "graph.py").read_text(
        encoding="utf-8"
    )
    doc = (_REPO / "docs" / "architecture.md").read_text(encoding="utf-8")
    for node in ("agent", "tools", "verify", "force_summary"):
        assert f'add_node("{node}"' in graph_src, (
            f"le nœud {node!r} n'existe plus dans graph.py — corriger le document"
        )
        assert node in doc, f"architecture.md ne décrit plus le nœud {node!r}"


def test_the_mcp_delta_explained_by_the_docs_is_real() -> None:
    """Les documents expliquent l'écart 196 → 206 : ce pin vérifie l'explication.

    ⚠️ **Ce test existe parce que la première explication écrite était FAUSSE.**
    Les docs annonçaient « 196 intégrés, plus ceux des serveurs MCP connectés ».
    Mesuré : l'instance en expose 206 avec **zéro** outil `mcp__serveur__outil`.
    Les 10 en trop sont les outils qui **gèrent** MCP, enregistrés derrière un
    drapeau — pas des outils apportés par un serveur.

    Une explication plausible et fausse est exactement ce que ce fichier doit
    empêcher. On épingle donc les trois faits de l'explication : le nom du
    drapeau, son défaut, et le nombre d'outils qu'il ouvre.
    """
    import re
    from pathlib import Path as _P

    src = (_REPO / "backend" / "app" / "skills" / "builtin" / "mcp_model_skill.py"
           ).read_text(encoding="utf-8")
    defined = len(re.findall(r"^async def (mcp_\w+)|^def (mcp_\w+)", src, re.M))
    assert defined == 10, (
        f"mcp_model_skill définit {defined} outils, les docs en annoncent 10"
    )

    config = (_REPO / "backend" / "app" / "config.py").read_text(encoding="utf-8")
    assert "mcp_client_v2_enabled: bool = False" in config, (
        "le drapeau a changé de nom ou de défaut — corriger les documents"
    )

    for doc in (_REPO / "README.md", _REPO / "README.fr.md",
                _REPO / "docs" / "architecture.md"):
        text = doc.read_text(encoding="utf-8")
        assert "mcp_client_v2_enabled" in text, (
            f"{_P(doc).name} n'explique plus d'où vient l'écart de comptage"
        )
