# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_disabling_a_skill_reaches_the_model.py
# @brief      L'interrupteur existait. Il n'était branché sur rien.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Tout était là sauf le fil (24/08).

    GET  /skills/                     liste les 45 compétences et leurs outils
    PUT  /skills/{nom}                écrit `SkillPreference.enabled`
    registry.get_user_active_tools()  lit les préférences et filtre

    $ grep -rn "get_user_active_tools" app/
    app/skills/registry.py:25:   - Expose ``get_user_active_tools()`` for …
    app/skills/registry.py:110:  async def get_user_active_tools(…)

**Zéro appelant.** La docstring du registre l'annonçait, la fonction était
correcte, personne ne l'appelait. Désactiver une compétence écrivait en base,
s'affichait à l'écran, et ne changeait rien à ce que le modèle recevait.

Quatrième occurrence du même motif ce mois-ci — #272 (fenêtre de contexte et
tarifs), #336 (modèle du tier A), #342 (modèle d'instance), celle-ci. **Une
écriture qui atteint la base sans atteindre le runtime.**

Preuve la plus parlante : la compétence `fibonacci` — un outil de test — est
marquée `enabled_by_default=False` **depuis toujours**. Elle partait quand même
dans le prompt à chaque tour, avec les 199 autres.

CE QUE CES PINS TIENNENT
-------------------------
1. Le fil lui-même, sur les DEUX voies. Une préférence qui vaudrait pour le
   cloud et pas pour le local serait un demi-interrupteur — pire qu'aucun,
   parce qu'on croirait avoir coupé.
2. **On échoue ouvert.** Base injoignable, table absente, requête qui lève :
   aucun outil n'est retiré. Un filtre qui échoue en RETIRANT rendrait Ely
   muette sur une panne de lecture.
3. **Jamais zéro outil en silence.** C'est la leçon d'Hermes #38798 : une
   migration de config y a réécrit un nom de toolset, `resolve_toolset` a rendu
   une liste vide, et *tous* les outils ont disparu sans une ligne de log —
   l'agent est retombé en texte seul et la cause a coûté un long débogage. Ici,
   un filtre qui viderait tout renonce et le dit fort.
4. Le compteur d'invalidation. Sans lui, le cache reproduirait exactement le
   défaut corrigé, un cran plus loin.

Run with:  cd backend && python -m pytest tests/test_disabling_a_skill_reaches_the_model.py -v
"""
from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest


def _outils(*noms):
    return [SimpleNamespace(name=n) for n in noms]


# ─────────────────────────────────────────────────────────────────────
# 1 — Le filtre lui-même
# ─────────────────────────────────────────────────────────────────────

def test_a_disabled_tool_is_removed():
    """LE pin. Ce que l'utilisateur coupe cesse de partir au modèle."""
    from app.skills.preferences_runtime import appliquer

    retenus = appliquer(
        _outils("web_search", "fibonacci", "weather_get"),
        frozenset({"fibonacci"}),
        contexte="test",
    )
    assert [t.name for t in retenus] == ["web_search", "weather_get"]


def test_nothing_disabled_returns_the_list_untouched():
    """Le cas courant doit être gratuit, et surtout ne rien réordonner."""
    from app.skills.preferences_runtime import appliquer

    entree = _outils("a", "b", "c")
    assert appliquer(entree, frozenset(), contexte="test") is entree


def test_the_filter_never_empties_a_non_empty_toolset(caplog):
    """⚠️ LA LEÇON D'HERMES #38798.

    Chez eux, une migration de config a réécrit un nom de toolset,
    `resolve_toolset` a rendu une liste vide, et **tous les outils ont disparu
    en silence** : aucune erreur, aucun log. L'agent a dégradé en répondeur
    texte et la cause a coûté un long débogage.

    Ici, un filtre qui retirerait tout renonce — et le dit fort. Un agent
    bruyamment incomplet vaut mieux qu'un agent silencieusement muet.
    """
    from app.skills.preferences_runtime import appliquer

    entree = _outils("a", "b")
    with caplog.at_level("WARNING"):
        retenus = appliquer(entree, frozenset({"a", "b"}), contexte="test")

    assert retenus is entree, "le filtre a vidé le catalogue"
    assert any("TOUS les outils" in r.message for r in caplog.records), (
        "le renoncement est silencieux — c'est exactement le défaut d'Hermes"
    )


@pytest.mark.asyncio
async def test_an_unreadable_database_removes_nothing(monkeypatch):
    """⚠️ ON ÉCHOUE OUVERT, et c'est un choix.

    Un filtre qui échoue en retirant des outils rendrait Ely incapable d'agir
    sur une simple panne de lecture — le pire échange possible. Sans
    préférences lisibles, on n'en applique aucune.
    """
    from app.skills import preferences_runtime as pr

    pr.vider_cache()

    class _BaseCassee:
        def __call__(self):
            raise RuntimeError("base injoignable")

    monkeypatch.setattr("app.database.async_session", _BaseCassee())
    assert await pr.disabled_tool_names("u-1") == frozenset()


@pytest.mark.asyncio
async def test_no_user_means_no_filtering():
    """Un appel d'API sans utilisateur ne doit pas hériter des préférences de
    personne."""
    from app.skills.preferences_runtime import disabled_tool_names

    assert await disabled_tool_names("") == frozenset()


# ─────────────────────────────────────────────────────────────────────
# 2 — Le compteur : sans lui, le cache recrée le défaut
# ─────────────────────────────────────────────────────────────────────

def test_the_version_counter_only_grows():
    """Les caches comparent par inégalité."""
    from app.skills import preferences_runtime as pr

    vus = [pr.get_preferences_version()]
    for _ in range(3):
        pr.bump_preferences_version()
        vus.append(pr.get_preferences_version())
    assert vus == sorted(vus) and len(set(vus)) == len(vus)


def test_the_write_endpoint_bumps_the_counter():
    """⚠️ LE SEUL LIEN entre l'interrupteur et le runtime.

    Sans cet incrément, la préférence est en base, l'écran l'affiche, et le
    cache continue de servir l'ancien état jusqu'au redémarrage — le défaut
    corrigé, reproduit un cran plus loin. Exactement ce qui est arrivé à
    `register_instance_cache` en #342.
    """
    from app.routers import skills as routeur

    src = inspect.getsource(routeur.update_skill)
    assert "bump_preferences_version()" in src, (
        "l'écriture de préférence n'invalide pas le cache — désactiver une "
        "compétence n'aura d'effet qu'au prochain redémarrage"
    )


def test_bumping_the_version_invalidates_the_cache(monkeypatch):
    """Le cache doit suivre le compteur, pas seulement l'utilisateur."""
    from app.skills import preferences_runtime as pr

    pr.vider_cache()
    pr._cache["u-1"] = (pr.get_preferences_version(), frozenset({"x"}))
    assert pr._cache["u-1"][0] == pr.get_preferences_version()

    pr.bump_preferences_version()
    assert pr._cache["u-1"][0] != pr.get_preferences_version(), (
        "l'entrée en cache reste valide après un changement de préférence"
    )
    pr.vider_cache()


# ─────────────────────────────────────────────────────────────────────
# 3 — Le câblage, sur les DEUX voies
# ─────────────────────────────────────────────────────────────────────

def test_both_paths_honour_the_preferences():
    """⚠️ Une préférence qui vaudrait pour le cloud et pas pour le local serait
    un DEMI-interrupteur — pire qu'aucun, parce qu'on croirait avoir coupé.

    Contrôle textuel : les deux liaisons vivent dans la même fonction, et c'est
    leur présence des deux côtés qui compte.
    """
    from app.agent import nodes

    src = inspect.getsource(nodes.create_agent_node)
    voie_slm = src.split("if use_slm:", 1)[1].split("if response is None:", 1)[0]
    voie_cloud = src.split("if response is None:", 1)[1]

    assert "disabled_tool_names(" in voie_slm, (
        "la voie locale ignore les préférences — une compétence coupée y "
        "reviendrait par la porte de derrière"
    )
    assert "disabled_tool_names(" in voie_cloud, "la voie cloud les ignore"
    assert voie_cloud.count("appliquer_preferences(") >= 1


def test_the_filter_runs_after_learned_tools_are_appended():
    """L'ordre compte : l'utilisateur doit pouvoir couper aussi ce qu'Ely s'est
    créé. Filtrer avant `append_learned_tools` laisserait les outils appris
    hors de portée de l'interrupteur — c'est-à-dire précisément ceux dont le
    nombre est appelé à croître."""
    from app.agent import nodes

    src = inspect.getsource(nodes.create_agent_node)
    apres = src.find("append_learned_tools(_filtered_tools")
    filtre = src.find("appliquer_preferences(", apres)
    assert apres != -1 and filtre != -1 and filtre > apres, (
        "le filtre des préférences ne couvre pas les outils appris"
    )


# ─────────────────────────────────────────────────────────────────────
# 4 — Le catalogue : ce qu'un outil coûte, ce qu'il a servi
# ─────────────────────────────────────────────────────────────────────

def test_the_catalog_route_is_declared_before_the_parameterised_one():
    """⚠️ FastAPI apparie dans l'ordre de déclaration.

    `PUT /{skill_name}` placé avant `GET /catalog` n'entre pas en conflit (les
    méthodes diffèrent), mais tout `GET /{…}` ajouté un jour au-dessus
    avalerait « catalog » comme un nom de compétence. Ce pin fige l'ordre
    pendant que c'est encore gratuit.
    """
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "app" / "routers" / "skills.py").read_text(
        encoding="utf-8",
    )
    catalogue = src.find('@router.get("/catalog")')
    parametree = src.find('@router.put("/{skill_name}")')
    assert catalogue != -1 and parametree != -1
    assert catalogue < parametree, (
        "la route paramétrée précède /catalog — une route GET paramétrée "
        "ajoutée là avalerait « catalog »"
    )


def test_the_cost_is_announced_as_an_approximation():
    """⚠️ Le vrai découpage dépend du tokenizer de chaque modèle. Un chiffre
    faux présenté comme exact ferait supprimer des outils sur du vent — le nom
    du champ porte donc l'incertitude."""
    from app.routers.skills import _approx_tokens

    outil = SimpleNamespace(description="x" * 400, args_schema=None)
    assert _approx_tokens(outil) == 100

    src = inspect.getsource(__import__("app.routers.skills", fromlist=["skills"]))
    assert '"approx_tokens"' in src and '"tokens"' not in src.replace('"approx_tokens"', ""), (
        "le champ doit s'appeler `approx_tokens`, pas `tokens`"
    )


def test_an_unreadable_schema_costs_zero_not_a_crash():
    """Un outil au schéma illisible ne doit pas faire tomber tout l'écran."""
    from app.routers.skills import _approx_tokens

    class _Casse:
        description = "abcd"

        @property
        def args_schema(self):
            raise RuntimeError("schéma illisible")

    assert _approx_tokens(_Casse()) == 1


# ─────────────────────────────────────────────────────────────────────
# 5 — La granularité par OUTIL (24/08)
# ─────────────────────────────────────────────────────────────────────

def test_a_tool_can_be_cut_inside_an_active_skill():
    """⚠️ CE PIN CORRIGE UN ARGUMENT DE LA #346.

    J'y avais écrit que la compétence était la bonne unité et que « 200
    interrupteurs seraient ingérables ». Le catalogue réel l'a réfuté :

        Gmail   21 outils   7 453 tk   234 appels   ← indispensable
                dont 9 jamais appelés : 2 433 tk à chaque tour

    Le poids mort ne se répartit pas par compétence — il se niche DANS les
    plus utilisées, parce que ce sont elles qui ont le plus d'outils. Aucun
    interrupteur par compétence ne peut l'atteindre.
    """
    import json

    from app.skills.preferences_runtime import _outils_coupes

    lignes = [SimpleNamespace(
        skill_name="google_gmail",
        config_json=json.dumps({"disabled_tools": ["gmail_update_settings"]}),
    )]
    assert _outils_coupes(lignes) == {
        "google_gmail": frozenset({"gmail_update_settings"}),
    }


@pytest.mark.parametrize("brut", [
    None, "", "{ pas du json", '{"disabled_tools": "pas une liste"}', "[]",
])
def test_a_corrupt_config_cuts_nothing(brut):
    """⚠️ Un JSON corrompu sur UNE compétence ne doit pas emporter les
    préférences des 44 autres, et surtout pas faire retirer des outils au
    hasard. On ignore l'entrée fautive et on la signale."""
    from app.skills.preferences_runtime import _outils_coupes

    lignes = [SimpleNamespace(skill_name="x", config_json=brut)]
    assert _outils_coupes(lignes).get("x", frozenset()) == frozenset()


def test_unknown_tool_names_are_refused_not_ignored():
    """⚠️ Une faute de frappe qui ne coupe rien EN SILENCE ferait croire à un
    réglage appliqué — la classe de défaut corrigée quatre fois ce mois-ci
    (#272, #336, #342, #346)."""
    from app.routers import skills as routeur

    src = inspect.getsource(routeur.update_skill_tools)
    assert "status_code=400" in src and "Outils inconnus" in src, (
        "un nom d'outil inconnu passe en silence"
    )


def test_the_per_tool_write_merges_instead_of_replacing():
    """⚠️ `PUT /{skill_name}` écrase `config_json` ENTIER. Laisser le frontend
    faire un lire-modifier-écrire ouvrirait une course entre deux onglets et
    perdrait toute autre clé de configuration au passage."""
    from app.routers import skills as routeur

    src = inspect.getsource(routeur.update_skill_tools)
    assert "json.loads(pref.config_json)" in src, (
        "la configuration existante n'est pas relue avant écriture"
    )
    assert 'conf["disabled_tools"] =' in src


def test_the_per_tool_write_also_bumps_the_counter():
    """Même invariant que l'interrupteur de compétence : sans incrément, le
    cache sert l'ancien état jusqu'au redémarrage."""
    from app.routers import skills as routeur

    assert "bump_preferences_version()" in inspect.getsource(routeur.update_skill_tools)


def test_the_catalog_reports_the_real_weight_of_a_skill():
    """Afficher le poids BRUT d'une compétence dont des outils sont coupés
    ferait croire que le réglage n'a rien changé. Le champ dédié existe."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "app" / "routers" / "skills.py").read_text(
        encoding="utf-8",
    )
    assert '"enabled_approx_tokens": sum(' in src, (
        "le catalogue ne rend pas le poids réel, coupures comprises"
    )
    assert '"never_called_count"' in src, (
        "sans ce compte, l'écran ne peut pas proposer de couper le poids mort"
    )
