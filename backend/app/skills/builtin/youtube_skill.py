# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/builtin/youtube_skill.py
# @brief      YouTube skill — search videos and retrieve transcripts.
#
# @author     Franck OLLIVIER <franck.olv@gmail.com>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
#             https://polyformproject.org/licenses/strict/1.0.0/
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
#   - INTERDIT : Toute utilisation commerciale sans accord préalable.
#   - INTERDIT : Redistribution de versions modifiées de ce code.
# =============================================================================
"""YouTube skill — search videos and retrieve transcripts."""
from app.skills.base import Skill
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
    tools=[
        youtube_search,
        youtube_transcript,
        youtube_video_info,
    ],
))
