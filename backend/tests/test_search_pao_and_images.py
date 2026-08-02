# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_search_pao_and_images.py
# @brief      La famille `pao`, le lien vers le FICHIER image, et l'aveu quand
#             le ciblage s'est perdu en route.
# @license    Elastic License 2.0
# =============================================================================
"""Pins de la recherche visuelle et du ciblage perdu.

Trois choses distinctes, qui échouent toutes les trois **en silence** :

1. **`pao` n'existe pas en amont.** SearXNG reconstruit son registre de
   catégories à chaque chargement depuis les moteurs déclarés — la nommer dans
   `config/searxng/settings.yml` suffit à la créer. Si plus aucun moteur ne la
   porte, la catégorie disparaît sans erreur et la requête retombe sur
   `general` : Ely continue de répondre, avec des images quelconques.

2. **Sur un moteur d'image, `url` est la PAGE, pas l'image.** Le fichier est
   dans `img_src`. Sans lui, `categories=images` rend des liens de galerie —
   la catégorie a l'air de marcher et ne sert à rien.

3. **Seul SearXNG sait cibler.** Les fournisseurs derrière ne prennent qu'une
   requête en texte. Une recherche `pao` qui descend jusqu'à eux remonte du web
   générique ; sans marqueur, le modèle la présenterait comme des sources
   qualifiées et proposerait à l'impression des images dont personne n'a
   vérifié la licence.

⚠️ Le pin le plus important est `test_le_ciblage_perdu_est_avoue` : c'est le
seul qui garde une **fausse déclaration** (invariant n°5 du dépôt) plutôt qu'un
simple confort.

Run with:  cd backend && python -m pytest tests/test_search_pao_and_images.py -v
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_CONF = (Path(__file__).resolve().parents[2] / "config" / "searxng"
         / "settings.yml")


class _S:
    """Réglages : SearXNG seul configuré, aucun fournisseur à crédits."""

    searxng_url = "http://searxng:8080"
    exa_api_key = ""
    serper_api_key = ""
    searchcans_api_key = ""
    google_search_api_key = ""
    google_search_cx = ""
    tavily_api_key = ""


# ── 1. la famille `pao` ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pao_est_transmise_et_sadditionne_aux_generalistes(monkeypatch) -> None:
    """`pao` part vers SearXNG, sans jamais évincer `general`.

    Une catégorie absente de `SEARCH_CATEGORIES` est filtrée en silence : si
    `pao` en sortait, la demande PAO deviendrait une recherche web ordinaire
    sans que rien ne le signale.
    """
    from app.agent.tools import search_tool as st

    vues: list[str] = []

    async def _capture(query: str, count: int, base_url: str,
                       categories: str = "general"):
        vues.append(categories)
        return [{"title": "t", "url": "https://ex.fr", "content": "c"}]

    monkeypatch.setattr(st, "_search_searxng", _capture)
    import app.config
    monkeypatch.setattr(app.config, "get_settings", lambda: _S())
    st.reset_quota_state()

    await st._dispatch_search("logo vectoriel libre de droits", 3, categories="pao")

    assert vues, "SearXNG n'a pas été appelé"
    assert "pao" in vues[0], (
        f"catégories transmises = {vues[0]!r} — « pao » a été filtrée, la "
        f"recherche PAO est retombée sur le web générique"
    )
    assert vues[0].split(",")[0] == "general", (
        f"« general » n'est plus en tête : {vues[0]!r}"
    )


def test_loutil_documente_la_famille_pao() -> None:
    """Le modèle ne demandera jamais `pao` s'il ignore qu'elle existe.

    La description part dans le prompt : c'est le seul endroit où le choix se
    joue.
    """
    from app.skills.builtin import register_all
    from app.skills import get_skill_registry

    register_all()
    outil = next(t for t in get_skill_registry().all_tools if t.name == "web_search")
    assert "pao" in (outil.description or "").lower(), (
        "la description ne mentionne pas « pao » — le modèle ne peut pas la choisir"
    )


# ── 2. le lien vers le fichier image ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_img_src_est_conserve(monkeypatch) -> None:
    """Le fichier image survit au passage par `_search_searxng`.

    SearXNG rend `url` (la page) ET `img_src` (le fichier). Ne garder que le
    premier rend `images` et `pao` inexploitables.
    """
    from app.agent.tools import search_tool as st

    class _Resp:
        @staticmethod
        def raise_for_status() -> None: ...

        @staticmethod
        def json() -> dict:
            return {"results": [{
                "title": "Affiche",
                "url": "https://commons.wikimedia.org/wiki/File:X.jpg",
                "content": "domaine public",
                "img_src": "https://upload.wikimedia.org/x.jpg",
            }]}

    class _Client:
        def __init__(self, *a, **k) -> None: ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a) -> None: ...
        async def get(self, url, params=None, headers=None): return _Resp()

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", _Client)

    out = await st._search_searxng("affiche", 3, "http://searxng:8080", "general,pao")

    assert out and out[0].get("img_src") == "https://upload.wikimedia.org/x.jpg", (
        f"img_src perdu : {out!r} — la catégorie image ne rend que des pages"
    )


def test_img_src_est_rendu_distinctement_du_lien_de_page() -> None:
    """Les deux liens sont affichés, et nommés — sinon le modèle les confond.

    Un seul des deux se télécharge ; présenter la page comme le fichier
    produirait un visuel manquant en bout de chaîne.
    """
    from app.agent.tools import search_tool as st

    texte = st._fmt_results([{
        "title": "Affiche",
        "url": "https://commons.wikimedia.org/wiki/File:X.jpg",
        "content": "domaine public",
        "img_src": "https://upload.wikimedia.org/x.jpg",
    }], "affiche", "SearXNG")

    assert "https://upload.wikimedia.org/x.jpg" in texte, "le fichier image n'est pas rendu"
    assert "https://commons.wikimedia.org/wiki/File:X.jpg" in texte, "la page a disparu"
    assert "image :" in texte, "le fichier n'est pas distingué de la page"


def test_un_resultat_sans_image_ne_gagne_pas_de_ligne_vide() -> None:
    """Le cas ordinaire — une recherche web — ne change pas de forme."""
    from app.agent.tools import search_tool as st

    texte = st._fmt_results(
        [{"title": "T", "url": "https://ex.fr", "content": "c"}], "q", "SearXNG",
    )
    assert "image :" not in texte


# ── 3. le ciblage perdu en cours de repli ─────────────────────────────────────

@pytest.mark.asyncio
async def test_le_ciblage_perdu_est_avoue(monkeypatch) -> None:
    """LE PIN QUI COMPTE — un repli ne se présente jamais comme un ciblage.

    Invariant n°5 : une fausse déclaration d'action est un bug. Dire « voici
    des images libres de droits » alors que la requête a fini sur DuckDuckGo,
    qui ne sait pas cibler, en est une.
    """
    from app.agent.tools import search_tool as st

    async def _searxng_muet(query: str, count: int, base_url: str,
                            categories: str = "general"):
        return None

    async def _ddgs(query: str, count: int):
        return [{"title": "t", "url": "https://ex.fr", "content": "c"}]

    monkeypatch.setattr(st, "_search_searxng", _searxng_muet)
    monkeypatch.setattr(st, "_search_ddgs", _ddgs)
    import app.config
    monkeypatch.setattr(app.config, "get_settings", lambda: _S())
    st.reset_quota_state()

    _, source = await st._dispatch_search("visuel libre", 3, categories="pao")

    assert st.is_unhonoured(source), (
        f"source = {source!r} — le ciblage perdu n'est pas signalé, le modèle "
        f"prendra des liens web ordinaires pour des sources qualifiées"
    )
    assert "pao" in source


@pytest.mark.asyncio
async def test_searxng_qui_repond_nest_jamais_marque(monkeypatch) -> None:
    """Le seul chemin qui honore vraiment le ciblage ne porte aucun marqueur.

    Un avertissement systématique serait vite ignoré — c'est ce qui vide un
    repli de sa valeur.
    """
    from app.agent.tools import search_tool as st

    async def _ok(query: str, count: int, base_url: str, categories: str = "general"):
        return [{"title": "t", "url": "https://ex.fr", "content": "c"}]

    monkeypatch.setattr(st, "_search_searxng", _ok)
    import app.config
    monkeypatch.setattr(app.config, "get_settings", lambda: _S())
    st.reset_quota_state()

    _, source = await st._dispatch_search("visuel", 3, categories="pao")
    assert source == "SearXNG"
    assert not st.is_unhonoured(source)


@pytest.mark.asyncio
async def test_sans_ciblage_demande_aucun_marqueur(monkeypatch) -> None:
    """Une recherche ordinaire tombée en repli n'a rien perdu de ciblé.

    Elle reste « dégradée » — c'est un autre message, et il existe déjà.
    """
    from app.agent.tools import search_tool as st

    async def _searxng_muet(query: str, count: int, base_url: str,
                            categories: str = "general"):
        return None

    async def _ddgs(query: str, count: int):
        return [{"title": "t", "url": "https://ex.fr", "content": "c"}]

    monkeypatch.setattr(st, "_search_searxng", _searxng_muet)
    monkeypatch.setattr(st, "_search_ddgs", _ddgs)
    import app.config
    monkeypatch.setattr(app.config, "get_settings", lambda: _S())
    st.reset_quota_state()

    _, source = await st._dispatch_search("capitale de la France", 3)

    assert not st.is_unhonoured(source), f"marqueur posé à tort : {source!r}"
    assert st.is_degraded(source), "le repli doit rester signalé comme dégradé"


# ── 4. la configuration qui fait exister tout ça ──────────────────────────────

def _engines() -> dict[str, dict]:
    conf = yaml.safe_load(_CONF.read_text(encoding="utf-8"))
    return {e["name"]: e for e in conf["engines"]}


def test_la_categorie_pao_est_portee_par_des_moteurs() -> None:
    """Sans moteur qui la nomme, `pao` n'existe pas — silencieusement.

    SearXNG construit `categories` depuis les moteurs déclarés
    (`engines/__init__.py`). Une catégorie que plus personne ne porte est
    ignorée, et la requête retombe sur `general` sans erreur.
    """
    eng = _engines()
    porteurs = [n for n, e in eng.items() if "pao" in (e.get("categories") or [])]

    assert "graphicdesign" in porteurs and "tex" in porteurs, (
        f"le savoir métier PAO a disparu de la catégorie : {porteurs}"
    )
    banques = {"openverse", "wikicommons.images", "artic", "unsplash", "pexels",
               "pixabay images", "public domain image archive",
               "library of congress"}
    assert banques <= set(porteurs), (
        f"banques d'images manquantes dans `pao` : {sorted(banques - set(porteurs))}"
    )


def test_les_moteurs_pao_restent_dans_images() -> None:
    """⚠️ `categories:` REMPLACE la liste, elle ne s'y ajoute pas.

    Écrire `categories: [pao]` sortirait ces moteurs de `images` — une
    recherche d'image ordinaire perdrait huit sources d'un coup, sans erreur.
    """
    eng = _engines()
    for nom in ("openverse", "wikicommons.images", "artic", "unsplash",
                "pexels", "pixabay images", "public domain image archive",
                "library of congress", "flaticon", "material icons"):
        cats = eng[nom].get("categories") or []
        assert "images" in cats, f"{nom} est sorti de `images` : {cats}"


def test_les_moteurs_pao_ne_sont_pas_redeclares() -> None:
    """On BASCULE UN DRAPEAU, on ne réécrit pas un moteur.

    Chaque moteur livré a ses paramètres propres (`wc_search_type`,
    `adobe_content_types`, `base_url`…). Les réécrire fait échouer le
    chargement — « can't register engine », arrivé quatre fois le 01/08.
    Seuls `graphicdesign` et `tex` sont des créations, et le module
    `stackexchange` exige alors `engine`, `api_site` et `shortcut`.
    """
    eng = _engines()
    autorisees = {"name", "categories", "disabled"}

    for nom, e in eng.items():
        if nom in ("graphicdesign", "tex"):
            assert e.get("engine") == "stackexchange"
            assert e.get("api_site") and e.get("shortcut")
            continue
        assert set(e) <= autorisees, (
            f"{nom} est redéclaré avec {sorted(set(e) - autorisees)} — "
            f"ses paramètres livrés seraient écrasés"
        )


def test_tineye_reste_hors_de_general() -> None:
    """TinEye prend une URL d'image, pas des mots — et sa catégorie amont est
    `general`.

    Activé tel quel, il recevrait CHAQUE recherche ordinaire d'Ely, avec ~9 s
    d'attente à la clé, pour ne jamais pouvoir y répondre.
    """
    cats = _engines()["tineye"].get("categories") or []
    assert cats and "general" not in cats, (
        f"tineye est dans `general` : {cats} — il intercepterait toutes les "
        f"recherches ordinaires"
    )


def test_aucun_moteur_inactif_en_amont_nest_active_naivement() -> None:
    """`disabled: false` NE LÈVE PAS `inactive: true`.

    `load_engines` fait `continue` avant même de charger le moteur. Et un
    moteur que ses mainteneurs marquent inactif est réputé cassé : l'activer
    produirait un moteur vert qui ne rend rien — le mode de panne que ce
    fichier combat.
    """
    eng = _engines()
    for nom in ("openclipart", "marginalia", "repology"):
        assert nom not in eng, (
            f"{nom} porte `inactive: true` en amont : l'activer exige "
            f"`inactive: false` en plus, et une vérification manuelle d'abord"
        )


def test_qwant_reste_ecarte() -> None:
    """Garde-fou contre une réactivation par mégarde.

    Qwant tape une API non documentée et se heurte à DataDome : CAPTCHA
    systématique (01/08). Le fichier a déjà été rouvert une fois sur une
    branche qui le réactivait.
    """
    assert _engines()["qwant"].get("disabled") is True
