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
