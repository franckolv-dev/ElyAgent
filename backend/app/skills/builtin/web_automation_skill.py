# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/builtin/web_automation_skill.py
# @brief      Automatisation web sans navigateur ouvert — la surface d'exposition
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Automatisation web « un coup » — chantier de la roadmap, livré le 22/08.

La roadmap disait : « Playwright est déjà là ; il manque la surface
d'exposition. Sert les tâches planifiées, qui ne peuvent pas dépendre d'un
navigateur ouvert. »

⚠️ Elle disait aussi que l'extension Chrome couvrait l'interactif et rien
d'autre — c'était inexact. `browser_skill` expose DÉJÀ `browser_screenshot` et
`browser_get_text` côté serveur, via Playwright. Le trou réel était plus
étroit : ces deux-là travaillent sur la page COURANTE d'une session
utilisateur, ce qu'une tâche planifiée n'a pas.

D'où quatre outils qui prennent l'URL en argument et n'ont besoin d'aucune
session. Les deux familles cohabitent, et chaque description dit laquelle
choisir — deux paires proches dans un catalogue de ~145 outils, c'est une
occasion de se tromper qu'on ferme par le texte.

Domaine RESEARCH : lire une page pour en tirer quelque chose est du même
ordre que `web_search`, et c'est le domaine que le routeur choisit pour les
demandes de veille.
"""
from app.agent.tools.web_tool import (
    web_compare,
    web_extract,
    web_screenshot,
    web_to_pdf,
)
from app.skills.base import Domain, Skill
from app.skills.registry import get_skill_registry

get_skill_registry().register(Skill(
    name="web_automation",
    display_name="Automatisation web",
    description=(
        "Capture, archive en PDF, lit et surveille une page web à partir de son "
        "URL, sans navigateur ouvert. Conçu pour les tâches planifiées et la "
        "veille : chaque outil ouvre la page, fait son travail et referme."
    ),
    icon="🌐",
    scopes=[],
    domains=[Domain.RESEARCH],
    tools=[
        web_screenshot,
        web_to_pdf,
        web_extract,
        web_compare,
    ],
))
