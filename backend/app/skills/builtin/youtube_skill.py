# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/builtin/youtube_skill.py
# @brief      YouTube skill — search videos and retrieve transcripts.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - AUTORISÉ : Modification et redistribution avec attribution.
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
"""YouTube skill — search videos and retrieve transcripts."""
from app.skills.base import Skill, Domain
from app.skills.registry import get_skill_registry
from app.agent.tools.youtube_tool import (
    youtube_search,
    youtube_transcript,
    youtube_video_info,
)

get_skill_registry().register(Skill(
    name="youtube",
    display_name="YouTube",
    description=(
        "Recherche des vidéos YouTube, récupère les transcriptions/sous-titres "
        "et les métadonnées d'une vidéo."
    ),
    icon="▶️",
    scopes=["internet"],
    domains=[Domain.CREATIVE],
    tools=[
        youtube_search,
        youtube_transcript,
        youtube_video_info,
    ],
))
