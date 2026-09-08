# =============================================================================
# @project    ELY — Exactly Like You
# @file       voice/xtts/tests/test_serveur.py
# @brief      Le service vocal local : découpe en phrases, registre des voix,
#             synthèse en WAV — le modèle est remplacé par un double.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""Run with:  cd voice/xtts && uv run --extra dev pytest -q"""
from __future__ import annotations

import io

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from serveur import Voix, creer_app, decouper_en_phrases

TAUX = 24_000


class _SynthFactice:
    """Rend une seconde de silence par phrase, et note ce qu'on lui demande."""

    def __init__(self) -> None:
        self.empreintes: list[list[str]] = []
        self.phrases: list[tuple[str, str]] = []

    def preparer(self, fichiers: list[str]) -> object:
        self.empreintes.append(list(fichiers))
        return ("empreinte", tuple(fichiers))

    def parler(self, texte: str, langue: str, empreinte: object) -> np.ndarray:
        self.phrases.append((texte, langue))
        return np.zeros(TAUX, dtype=np.float32)


@pytest.fixture
def dossier_voix(tmp_path):
    for nom in ("gert", "test"):
        d = tmp_path / nom
        d.mkdir()
        sf.write(d / "ref.wav", np.zeros(TAUX * 2, dtype=np.float32), TAUX)
    (tmp_path / "vide").mkdir()  # sans fichier audio : pas une voix
    return tmp_path


# ── La découpe ───────────────────────────────────────────────────────────────


def test_decouper_en_phrases_suit_la_ponctuation():
    texte = "Bonjour Franck, c'est Ely. Tu veux que je réserve la salle ? Bien sûr, je m'en occupe ! Voilà qui est fait."
    assert decouper_en_phrases(texte) == [
        "Bonjour Franck, c'est Ely.",
        "Tu veux que je réserve la salle ?",
        "Bien sûr, je m'en occupe !",
        "Voilà qui est fait.",
    ]


def test_decouper_ne_coupe_pas_sur_un_nombre_ni_une_abreviation():
    assert decouper_en_phrases("Rendez-vous à 14h30. Tarif : 12.50 euros, M. Dupont confirme.") == [
        "Rendez-vous à 14h30.",
        "Tarif : 12.50 euros, M. Dupont confirme.",
    ]


def test_decouper_regroupe_les_miettes_et_borne_les_longues():
    court = decouper_en_phrases("Oui. Non. Peut-être.")
    assert court == ["Oui. Non. Peut-être."], "trois miettes = une seule synthèse"
    longue = "mot " * 200
    morceaux = decouper_en_phrases(longue.strip())
    assert len(morceaux) >= 2 and all(len(m) <= 300 for m in morceaux)


def test_decouper_rend_vide_pour_un_texte_vide():
    assert decouper_en_phrases("   \n ") == []


# ── Les voix ─────────────────────────────────────────────────────────────────


def test_le_registre_lit_les_dossiers_qui_ont_un_audio(dossier_voix):
    synth = _SynthFactice()
    voix = Voix(dossier_voix, synth)
    assert voix.noms() == ["gert", "test"]
    assert synth.empreintes == [], "l'empreinte se calcule à la première demande"
    voix.empreinte("gert")
    voix.empreinte("gert")
    assert len(synth.empreintes) == 1, "une empreinte se calcule une fois, puis se garde"
    with pytest.raises(KeyError):
        voix.empreinte("inconnue")


# ── L'API ────────────────────────────────────────────────────────────────────


@pytest.fixture
def client(dossier_voix):
    synth = _SynthFactice()
    app = creer_app(synth, dossier_voix, voix_par_defaut="gert", appareil="mps")
    return TestClient(app), synth


def test_health_dit_l_etat(client):
    c, _ = client
    r = c.get("/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["voices"] == ["gert", "test"]
    assert r.json()["default_voice"] == "gert"
    assert r.json()["device"] == "mps"


def test_speak_rend_un_wav_de_toutes_les_phrases(client):
    c, synth = client
    r = c.post("/speak", json={"text": "Bonjour Franck. Tu as un point à 14h. À plus tard !"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("audio/wav")
    audio, taux = sf.read(io.BytesIO(r.content), dtype="float32")
    assert taux == TAUX
    # trois phrases d'une seconde + deux pauses entre elles
    assert 3.4 <= len(audio) / taux <= 4.0
    assert [p for p, _l in synth.phrases] == ["Bonjour Franck.", "Tu as un point à 14h.", "À plus tard !"]
    assert all(langue == "fr" for _p, langue in synth.phrases)


def test_speak_choisit_la_voix_et_la_langue(client):
    c, synth = client
    r = c.post("/speak", json={"text": "Hello there.", "voice": "test", "language": "en"})
    assert r.status_code == 200
    assert synth.empreintes[-1][0].endswith("test/ref.wav")
    assert synth.phrases[-1] == ("Hello there.", "en")


def test_speak_refuse_une_voix_inconnue_et_un_texte_vide(client):
    c, _ = client
    assert c.post("/speak", json={"text": "Bonjour.", "voice": "nadia"}).status_code == 404
    assert c.post("/speak", json={"text": "   "}).status_code == 400


def test_voices_liste_les_voix(client):
    c, _ = client
    assert c.get("/voices").json() == {"voices": ["gert", "test"], "default_voice": "gert"}


def test_deux_demandes_en_meme_temps_ne_se_marchent_pas_dessus(dossier_voix):
    """Deux inférences MPS en parallèle font s'effondrer le processus : le
    service les sérialise. Le double lève s'il est réentré."""
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor

    class _SynthJaloux(_SynthFactice):
        def __init__(self) -> None:
            super().__init__()
            self.occupe = threading.Lock()

        def parler(self, texte, langue, empreinte):
            if not self.occupe.acquire(blocking=False):
                raise RuntimeError("réentré : deux synthèses en même temps")
            try:
                time.sleep(0.05)
                return super().parler(texte, langue, empreinte)
            finally:
                self.occupe.release()

    synth = _SynthJaloux()
    c = TestClient(creer_app(synth, dossier_voix, voix_par_defaut="gert"))
    with ThreadPoolExecutor(max_workers=4) as pool:
        codes = list(pool.map(
            lambda i: c.post("/speak", json={"text": f"Phrase numéro {i}, assez longue."}).status_code,
            range(4),
        ))
    assert codes == [200, 200, 200, 200]
    assert len(synth.phrases) == 4
