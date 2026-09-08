# =============================================================================
# @project    ELY — Exactly Like You
# @file       voice/xtts/serveur.py
# @brief      Service local de synthèse vocale : XTTS-v2 et une voix clonée,
#             sur la machine, exposés en HTTP au backend d'Ely.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""La voix d'Ely, sur la machine (08/09/2026).

Jusqu'ici Ely parlait par edge-tts : une voix Microsoft, synthétique, et
chaque réponse lue partait chez Microsoft. Ce service fait tourner XTTS-v2
(Coqui, licence publique non commerciale) sur le Mac avec la voix clonée
d'une personne consentante : le texte et la voix ne quittent plus la
machine.

Pourquoi hors du conteneur : Docker n'a pas accès au GPU du Mac, et le
modèle plus torch pèsent trois gigaoctets. Le service vit sur l'hôte comme
LM Studio, et le backend l'appelle sur ``host.docker.internal``.

Mesuré le 08/09 sur un M1 Max, MPS, empreinte pré-calculée : 1,3 à 2,5 s de
calcul par phrase pour 3 à 5 s d'audio. C'est plus vite que le temps réel,
mais seulement phrase par phrase : le client découpe et demande chaque
phrase, ce service en fait autant sur un texte long.

Contrat :
    GET  /health            → {ok, device, voices, default_voice, model_loaded}
    GET  /voices            → {voices, default_voice}
    POST /speak             → audio/wav 24 kHz mono
         {"text": …, "voice": "gert", "language": "fr"}

Une voix = un dossier ``voices/<nom>/`` contenant un ou plusieurs ``.wav``
de référence (10 à 30 s de parole propre). Son empreinte est calculée à la
première demande puis gardée en mémoire. Le dossier ``voices/`` n'est pas
suivi par git : ces enregistrements restent ici.
"""
from __future__ import annotations

import io
import logging
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Protocol

import numpy as np
import soundfile as sf
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

logger = logging.getLogger("ely.voix")

TAUX = 24_000                 # Hz — la sortie native de XTTS-v2
PAUSE_ENTRE_PHRASES = 0.25    # s
_LONGUEUR_MAX = 300           # car. — au-delà, XTTS dérive ; on coupe à la virgule
_MIETTE = 12                  # car. — en dessous, on colle à la phrase suivante

# ── Découpe en phrases ───────────────────────────────────────────────────────

# Une frontière : ponctuation forte suivie d'une espace. « M. Dupont » et
# « 12.50 » ne sont pas des frontières : abréviation d'une ou deux lettres
# majuscules, ou point collé à un chiffre.
_FRONTIERE = re.compile(r"(?<![A-ZÀ-Ý]\.)(?<![A-ZÀ-Ý][a-zà-ÿ]\.)(?<=[.!?…])\s+(?=\S)")


def decouper_en_phrases(texte: str) -> list[str]:
    """Les phrases à synthétiser une par une, miettes recollées, longues coupées."""
    plat = " ".join((texte or "").split())
    if not plat:
        return []
    brutes = [m.strip() for m in _FRONTIERE.split(plat) if m.strip()]

    # Les miettes (« Oui. ») se collent à la phrase suivante : une synthèse
    # de quatre caractères coûte autant qu'une de quarante.
    collees: list[str] = []
    en_cours = ""
    for b in brutes:
        en_cours = f"{en_cours} {b}".strip() if en_cours else b
        if len(en_cours) >= _MIETTE:
            collees.append(en_cours)
            en_cours = ""
    if en_cours:
        if collees:
            collees[-1] = f"{collees[-1]} {en_cours}"
        else:
            collees.append(en_cours)

    bornees: list[str] = []
    for c in collees:
        bornees.extend(_couper_longue(c))
    return bornees


def _couper_longue(phrase: str) -> list[str]:
    if len(phrase) <= _LONGUEUR_MAX:
        return [phrase]
    morceaux: list[str] = []
    reste = phrase
    while len(reste) > _LONGUEUR_MAX:
        fenetre = reste[:_LONGUEUR_MAX]
        coupe = max(fenetre.rfind(", "), fenetre.rfind("; "), fenetre.rfind(" : "))
        if coupe < _LONGUEUR_MAX // 3:
            coupe = fenetre.rfind(" ")
        if coupe <= 0:
            coupe = _LONGUEUR_MAX
        morceaux.append(reste[:coupe].strip(" ,;:"))
        reste = reste[coupe:].strip(" ,;:")
    if reste:
        morceaux.append(reste)
    return morceaux


# ── Le synthétiseur ──────────────────────────────────────────────────────────


class Synthetiseur(Protocol):
    def preparer(self, fichiers: list[str]) -> object: ...
    def parler(self, texte: str, langue: str, empreinte: object) -> np.ndarray: ...


class SynthetiseurXtts:
    """XTTS-v2 via coqui-tts. Import paresseux : les tests n'en ont pas besoin."""

    def __init__(self, appareil: str = "mps") -> None:
        from TTS.api import TTS  # noqa: PLC0415 — trois gigaoctets, à la demande

        os.environ.setdefault("COQUI_TOS_AGREED", "1")
        t0 = time.monotonic()
        self._tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2")
        try:
            self._tts.to(appareil)
            self.appareil = appareil
        except Exception as exc:  # noqa: BLE001 — MPS absent : le CPU marche, en plus lent
            logger.warning("appareil %s indisponible (%s) — CPU", appareil, exc)
            self._tts.to("cpu")
            self.appareil = "cpu"
        self._modele = self._tts.synthesizer.tts_model
        logger.info("XTTS-v2 chargé en %.0f s sur %s", time.monotonic() - t0, self.appareil)

    def preparer(self, fichiers: list[str]) -> object:
        gpt_cond, spk = self._modele.get_conditioning_latents(audio_path=fichiers, max_ref_length=30)
        return (gpt_cond, spk)

    def parler(self, texte: str, langue: str, empreinte: object) -> np.ndarray:
        gpt_cond, spk = empreinte  # type: ignore[misc]
        sortie = self._modele.inference(texte, langue, gpt_cond, spk, temperature=0.7)
        wav = sortie["wav"]
        if hasattr(wav, "cpu"):
            wav = wav.cpu().numpy()
        return np.asarray(wav, dtype=np.float32)


# ── Les voix ─────────────────────────────────────────────────────────────────


class Voix:
    """Le registre des voix : un dossier par voix, l'empreinte gardée en mémoire."""

    def __init__(self, dossier: Path, synth: Synthetiseur) -> None:
        self._dossier = Path(dossier)
        self._synth = synth
        self._empreintes: dict[str, object] = {}

    def fichiers(self, nom: str) -> list[str]:
        d = self._dossier / nom
        if not d.is_dir():
            return []
        return sorted(str(p) for p in d.glob("*.wav"))

    def noms(self) -> list[str]:
        if not self._dossier.is_dir():
            return []
        return sorted(p.name for p in self._dossier.iterdir() if p.is_dir() and self.fichiers(p.name))

    def empreinte(self, nom: str) -> object:
        if nom in self._empreintes:
            return self._empreintes[nom]
        fichiers = self.fichiers(nom)
        if not fichiers:
            raise KeyError(nom)
        t0 = time.monotonic()
        self._empreintes[nom] = self._synth.preparer(fichiers)
        logger.info("empreinte de la voix « %s » calculée en %.1f s (%d fichier(s))",
                    nom, time.monotonic() - t0, len(fichiers))
        return self._empreintes[nom]


# ── L'API ────────────────────────────────────────────────────────────────────


class DemandeParole(BaseModel):
    text: str
    voice: str | None = None
    language: str = Field("fr", min_length=2, max_length=5)


def _wav(audio: np.ndarray) -> bytes:
    tampon = io.BytesIO()
    sf.write(tampon, audio, TAUX, format="WAV", subtype="PCM_16")
    return tampon.getvalue()


def creer_app(synth: Synthetiseur, dossier_voix: Path, *, voix_par_defaut: str = "", appareil: str = "") -> FastAPI:
    app = FastAPI(title="Ely — voix locale", version="0.1.0")
    voix = Voix(dossier_voix, synth)
    app.state.voix = voix
    # Une synthèse à la fois : deux inférences MPS en parallèle font
    # s'effondrer le processus (« A command encoder is already encoding to
    # this command buffer », 08/09/2026). Les appels s'attendent, ils ne se
    # marchent pas dessus.
    verrou = threading.Lock()
    app.state.verrou = verrou

    def _defaut() -> str:
        noms = voix.noms()
        if voix_par_defaut and voix_par_defaut in noms:
            return voix_par_defaut
        return noms[0] if noms else ""

    @app.get("/health")
    def health() -> dict:
        return {"ok": True, "device": appareil, "voices": voix.noms(),
                "default_voice": _defaut(), "model_loaded": True}

    @app.get("/voices")
    def voices() -> dict:
        return {"voices": voix.noms(), "default_voice": _defaut()}

    @app.post("/speak")
    def speak(demande: DemandeParole) -> Response:
        phrases = decouper_en_phrases(demande.text)
        if not phrases:
            raise HTTPException(status_code=400, detail="texte vide")
        nom = demande.voice or _defaut()
        try:
            empreinte = voix.empreinte(nom)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"voix inconnue : {nom!r}")
        pause = np.zeros(int(TAUX * PAUSE_ENTRE_PHRASES), dtype=np.float32)
        morceaux: list[np.ndarray] = []
        t0 = time.monotonic()
        with verrou:
            for i, phrase in enumerate(phrases):
                if i:
                    morceaux.append(pause)
                morceaux.append(synth.parler(phrase, demande.language, empreinte))
        audio = np.concatenate(morceaux) if morceaux else np.zeros(0, dtype=np.float32)
        logger.info("« %s » : %d phrase(s), %.1f s d'audio en %.1f s",
                    nom, len(phrases), len(audio) / TAUX, time.monotonic() - t0)
        return Response(content=_wav(audio), media_type="audio/wav")

    return app


def main() -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ici = Path(__file__).parent
    dossier = Path(os.environ.get("XTTS_VOICES_DIR", ici / "voices"))
    appareil = os.environ.get("XTTS_DEVICE", "mps")
    port = int(os.environ.get("XTTS_PORT", "8020"))
    defaut = os.environ.get("XTTS_DEFAULT_VOICE", "")
    synth = SynthetiseurXtts(appareil)
    app = creer_app(synth, dossier, voix_par_defaut=defaut, appareil=synth.appareil)
    for nom in app.state.voix.noms():
        app.state.voix.empreinte(nom)  # à chaud avant la première demande
    uvicorn.run(app, host=os.environ.get("XTTS_HOST", "127.0.0.1"), port=port, log_level="info")


if __name__ == "__main__":
    sys.exit(main())
