"""Couche 2 NER du SecurityFilter (PII_NER_ENABLED) — pins de comportement.

Le vrai modèle (GLiNER ONNX, tire torch) n'est PAS installé dans le venv de
test : ces tests utilisent un faux modèle qui REJOUE les détections validées
par le bench du 2026-06-10 (PyTorch fp32, M1 Max — scripts/bench_pii_ner.py),
y compris ses deux comportements documentés :

- l'incohérence de seuil (« Sophie » scorée 0.46-0.72 selon l'occurrence)
  → corrigée par le remplacement vault-first ;
- le faux positif « Pierre » dans le proverbe « Pierre qui roule » (0.99)
  → ACCEPTABLE car le placeholder est réversible (pin dédié).

Ce qui est pinné ici est donc le PIPELINE (flag, vault-first, cache,
placeholders, réversibilité) au-dessus d'un modèle au comportement connu —
la qualité du modèle lui-même a été validée par le bench, pas par pytest.

Run with:  cd backend && python -m pytest tests/test_pii_ner_layer.py -v
"""
import pytest

from app.services import pii_ner
from app.services.pii_ner import PIINEREngine, load_ner_engine, unload_ner_engine
from app.services.security_filter import SecurityFilter


# ── Faux modèle : rejoue le bench ─────────────────────────────────────────────

class FakeGLiNERModel:
    """Détections canned (valeur, label gliner, score[, require]).

    Une entrée n'est « détectée » dans un texte que si la valeur s'y trouve
    ET que le score passe le seuil ET (optionnel) que le texte contient
    ``require`` — ce qui permet de simuler le score dépendant du contexte
    observé au bench (Sophie 0.72 avec son titre, 0.46 sans).
    Compte les appels pour les pins de cache.
    """

    def __init__(self, canned):
        self.canned = canned
        self.calls = 0

    def predict_entities(self, text, labels, threshold=0.5):
        self.calls += 1
        out = []
        for entry in self.canned:
            value, label, score = entry[0], entry[1], entry[2]
            require = entry[3] if len(entry) > 3 else None
            if score < threshold or (require and require not in text):
                continue
            idx = text.find(value)
            while idx != -1:
                out.append({
                    "start": idx, "end": idx + len(value),
                    "text": value, "label": label, "score": score,
                })
                idx = text.find(value, idx + 1)
        return out


# Corpus bench 2026-06-10 — scores mesurés en réel.
BENCH_CANNED = [
    ("Mme Élodie Rousseau", "person", 1.00),
    ("cabinet Durand & Associés", "organization", 0.96),
    ("TotalEnergies", "organization", 0.99),
    ("12 rue de la République, 33000 Bordeaux", "address", 0.99),
    ("Pierre", "person", 0.99),                       # faux positif proverbe
    ("Marion", "person", 0.99),
    ("Decathlon", "organization", 0.97),
    # Incohérence de seuil mesurée : détectée seulement avec son contexte
    # (« directrice ») — l'occurrence nue score 0.46, sous le seuil 0.5.
    ("Sophie Lefebvre", "person", 0.72, "directrice"),
]


@pytest.fixture
def fake_model():
    return FakeGLiNERModel(BENCH_CANNED)


@pytest.fixture
def ner_on(monkeypatch, fake_model):
    """Flag posé + moteur installé avec le faux modèle bench."""
    monkeypatch.setenv("PII_NER_ENABLED", "1")
    monkeypatch.setattr(pii_ner, "_engine", PIINEREngine(fake_model))
    return fake_model


@pytest.fixture
def sf():
    return SecurityFilter()


# ── Pin : flag off = comportement strictement identique à aujourd'hui ─────────

class TestFlagOff:
    def test_names_untouched_and_zero_ner_calls(self, monkeypatch, fake_model, sf):
        """Flag absent : même avec un moteur chargé en mémoire, anonymize()
        ne le consulte JAMAIS et la sortie est celle de la couche 1 seule."""
        monkeypatch.delenv("PII_NER_ENABLED", raising=False)
        monkeypatch.setattr(pii_ner, "_engine", PIINEREngine(fake_model))
        text = "Réunion avec Mme Élodie Rousseau (TotalEnergies), mail elodie@total.fr"
        result = sf.anonymize(text)
        assert result == "Réunion avec Mme Élodie Rousseau (TotalEnergies), mail [EMAIL_0]"
        assert fake_model.calls == 0
        assert list(sf._vault.values()) == ["elodie@total.fr"]

    @pytest.mark.parametrize("value", ["", "0", "false", "no", "off"])
    def test_falsy_flag_values(self, monkeypatch, fake_model, sf, value):
        monkeypatch.setenv("PII_NER_ENABLED", value)
        monkeypatch.setattr(pii_ner, "_engine", PIINEREngine(fake_model))
        text = "Appelle Pierre demain."
        assert sf.anonymize(text) == text
        assert fake_model.calls == 0

    def test_flag_on_engine_missing_fails_open(self, monkeypatch, sf):
        """Flag posé mais moteur jamais chargé (boot raté / modèle absent) :
        fail-open, la couche 1 regex reste seule — jamais d'exception."""
        monkeypatch.setenv("PII_NER_ENABLED", "1")
        monkeypatch.setattr(pii_ner, "_engine", None)
        text = "Contacte Mme Élodie Rousseau sur elodie@total.fr"
        assert sf.anonymize(text) == "Contacte Mme Élodie Rousseau sur [EMAIL_0]"


# ── Pins de détection FR (corpus bench) ──────────────────────────────────────

class TestDetectionFR:
    def test_person_with_civility(self, ner_on, sf):
        result = sf.anonymize("Le dossier de Mme Élodie Rousseau est prêt.")
        assert "Élodie Rousseau" not in result
        assert result == "Le dossier de [PERSON_0] est prêt."

    def test_organization_cabinet(self, ner_on, sf):
        result = sf.anonymize("Le cabinet Durand & Associés a répondu.")
        assert "Durand" not in result
        assert "[ORG_0]" in result

    def test_organization_known_brand(self, ner_on, sf):
        result = sf.anonymize("Réunion avec TotalEnergies jeudi à 14h.")
        assert result == "Réunion avec [ORG_0] jeudi à 14h."

    def test_address(self, ner_on, sf):
        result = sf.anonymize("Envoyez tout au 12 rue de la République, 33000 Bordeaux.")
        assert "République" not in result
        assert result == "Envoyez tout au [ADDRESS_0]."

    def test_both_layers_share_counter_and_vault(self, ner_on, sf):
        """Couche 1 (regex) et couche 2 (NER) posent leurs placeholders dans
        le MÊME vault avec le MÊME compteur — pas de collision possible.
        (La numérotation suit l'ordre de substitution droite→gauche, comme
        la couche 1 depuis toujours — seule la STABILITÉ compte.)"""
        result = sf.anonymize("Mme Élodie Rousseau (elodie@total.fr) chez TotalEnergies.")
        assert result == "[PERSON_2] ([EMAIL_0]) chez [ORG_1]."
        assert sf._vault == {
            "[EMAIL_0]": "elodie@total.fr",
            "[ORG_1]": "TotalEnergies",
            "[PERSON_2]": "Mme Élodie Rousseau",
        }


# ── Pin : faux positif proverbe — documenté comme ACCEPTABLE ─────────────────

class TestProverbFalsePositive:
    def test_pierre_qui_roule_is_masked_but_reversible(self, ner_on, sf):
        """Le bench détecte « Pierre » à 0.99 dans « Pierre qui roule
        n'amasse pas mousse » — faux positif inévitable (homonymie
        prénom/nom commun), ACCEPTÉ car le placeholder est réversible :
        le LLM perd un mot du proverbe, l'utilisateur ne perd rien
        (deanonymize restitue le texte exact). NE PAS « corriger » en
        montant le seuil : à 0.7 on perd de vraies personnes du bench."""
        original = "Pierre qui roule n'amasse pas mousse."
        result = sf.anonymize(original)
        assert result == "[PERSON_0] qui roule n'amasse pas mousse."
        assert sf.deanonymize(result) == original


# ── Pin vault-first : « Sophie » cohérente entre occurrences ─────────────────

class TestVaultFirst:
    def test_sophie_masked_even_when_ner_misses(self, ner_on, sf):
        """Bench : « Sophie Lefebvre » score 0.72 avec son titre, 0.46 nue
        — sous le seuil, le NER seul la laissait fuiter une fois sur deux.
        Une fois dans le vault, TOUTES les occurrences futures sont
        masquées par recherche directe, avec le MÊME placeholder."""
        r1 = sf.anonymize("Profil : Sophie Lefebvre, directrice marketing chez Decathlon.")
        assert "Sophie" not in r1
        assert "[PERSON_1]" in r1 and "[ORG_0]" in r1

        # Le faux modèle ne détecte RIEN ici (pas de « directrice » → 0.46).
        r2 = sf.anonymize("Rappelle Sophie Lefebvre demain matin.")
        assert r2 == "Rappelle [PERSON_1] demain matin."

    def test_vault_first_respects_word_boundaries(self, ner_on, sf):
        """« Marion » au vault ne doit pas mutiler « Marionnettes »."""
        sf.anonymize("Va chercher Marion à la gare.")
        result = sf.anonymize("Le spectacle de Marionnettes est complet.")
        assert result == "Le spectacle de Marionnettes est complet."

    def test_longest_candidate_wins_at_same_position(self, ner_on, sf):
        """Si « Sophie Lefebvre » (nouvelle détection) et « Sophie »
        (hypothétique entrée vault) matchent à la même position, c'est le
        plus long qui est remplacé — pas de placeholder imbriqué."""
        sf._vault["[PERSON_0]"] = "Sophie"
        sf._counter = 1
        result = sf.anonymize("Sophie Lefebvre, directrice, confirme.")
        assert result == "[PERSON_1], directrice, confirme."
        assert sf._vault["[PERSON_1]"] == "Sophie Lefebvre"


# ── Pin cache : 2e anonymisation du même texte = 0 appel NER ─────────────────

class TestCache:
    def test_second_anonymize_zero_ner_calls(self, ner_on, sf):
        text = "Réunion avec TotalEnergies jeudi à 14h."
        sf.anonymize(text)
        calls_after_first = ner_on.calls
        assert calls_after_first >= 1
        r2 = sf.anonymize(text)
        assert ner_on.calls == calls_after_first   # 0 appel NER au 2e passage
        assert "[ORG_0]" in r2                      # mais toujours anonymisé

    def test_cache_shared_across_conversations(self, ner_on):
        """Le cache est par TEXTE (global moteur) : la même phrase dans une
        autre conversation est un hit. Les mappings restent par-conversation
        (chaque filtre a son vault → placeholders indépendants)."""
        text = "Réunion avec TotalEnergies jeudi à 14h."
        sf1, sf2 = SecurityFilter(), SecurityFilter()
        sf1.anonymize(text)
        calls = ner_on.calls
        r2 = sf2.anonymize(text)
        assert ner_on.calls == calls
        assert "[ORG_0]" in r2
        assert sf1._vault is not sf2._vault

    def test_hot_path_history_replay(self, ner_on):
        """Simulation du chemin chaud chat.py : ~40 messages d'historique
        ré-anonymisés à chaque tour. Tour 2 = 100 % de hits, 0 inférence."""
        history = [f"Message {i} : réunion avec TotalEnergies le {i} juin." for i in range(40)]
        sf_conv = SecurityFilter()
        for msg in history:
            sf_conv.anonymize(msg)
        calls_turn_1 = ner_on.calls
        for msg in history:
            sf_conv.anonymize(msg)
        assert ner_on.calls == calls_turn_1


# ── Pin réversibilité ─────────────────────────────────────────────────────────

class TestReversibility:
    def test_full_round_trip_both_layers(self, ner_on, sf):
        original = (
            "Mme Élodie Rousseau (TotalEnergies) — mail elodie@total.fr, "
            "tel 06 12 34 56 78, bureau au 12 rue de la République, 33000 Bordeaux."
        )
        anonymized = sf.anonymize(original)
        for leaked in ("Élodie", "TotalEnergies", "elodie@total.fr",
                       "06 12 34 56 78", "République"):
            assert leaked not in anonymized
        assert sf.deanonymize(anonymized) == original

    def test_anonymize_is_idempotent_on_anonymized_text(self, ner_on, sf):
        """Re-anonymiser un texte déjà anonymisé ne touche à rien : jamais
        de substitution à l'intérieur d'un placeholder existant (c'est le
        chemin réel des messages assistant re-soumis au LLM)."""
        anonymized = sf.anonymize("Mme Élodie Rousseau travaille chez TotalEnergies.")
        assert sf.anonymize(anonymized) == anonymized

    def test_placeholder_stable_across_messages(self, ner_on, sf):
        r1 = sf.anonymize("Mme Élodie Rousseau a appelé.")
        r2 = sf.anonymize("Rappelle Mme Élodie Rousseau ce soir.")
        assert "[PERSON_0]" in r1 and "[PERSON_0]" in r2


# ── Moteur : unités (chunking, plafond, filtres) ──────────────────────────────

class TestEngineInternals:
    def test_long_text_is_chunked(self):
        """Au-delà de ~1200 chars le modèle tronquerait silencieusement —
        le moteur découpe et voit donc les entités des chunks suivants."""
        fake = FakeGLiNERModel([("TotalEnergies", "organization", 0.99)])
        engine = PIINEREngine(fake)
        text = ("Lorem ipsum dolor sit amet. " * 60) + " Contrat signé avec TotalEnergies hier."
        assert len(text) > 1200
        result = engine.extract(text)
        assert ("TotalEnergies", "ORG") in result
        assert fake.calls >= 2  # au moins 2 chunks soumis

    def test_ner_coverage_cap(self, monkeypatch):
        """PII_NER_MAX_CHARS borne la latence sur les gros résultats
        d'outils : au-delà du plafond, le NER ne voit plus le texte (la
        couche 1 regex, elle, couvre toujours tout)."""
        monkeypatch.setenv("PII_NER_MAX_CHARS", "100")
        fake = FakeGLiNERModel([("TotalEnergies", "organization", 0.99)])
        engine = PIINEREngine(fake)
        text = ("x" * 200) + " TotalEnergies"
        assert engine.extract(text) == []

    def test_placeholder_shaped_values_filtered(self):
        fake = FakeGLiNERModel([("[PERSON_0]", "person", 0.99)])
        engine = PIINEREngine(fake)
        assert engine.extract("Rappelle [PERSON_0] demain.") == []

    def test_values_deduplicated(self):
        fake = FakeGLiNERModel([("Pierre", "person", 0.99)])
        engine = PIINEREngine(fake)
        result = engine.extract("Pierre a vu Pierre.")
        assert result == [("Pierre", "PERSON")]

    def test_empty_text_no_model_call(self):
        fake = FakeGLiNERModel([])
        engine = PIINEREngine(fake)
        assert engine.extract("") == []
        assert engine.extract("   ") == []
        assert fake.calls == 0


# ── Pin : contenu machine = vault-first seulement, pas de détection fraîche ──

class TestMachineContentMode:
    """Retour terrain 2026-06-11 : la détection NER fraîche sur les résultats
    d'outils masquait chaque personne/org du web, des emails et de GitHub —
    briefing illisible ([ORG_n] partout) et agent cassé. Le contenu machine
    passe en ``ner_detection=False`` : regex + vault-first restent actifs."""

    def test_no_fresh_detection_on_machine_content(self, ner_on, sf):
        text = "Stargazers : Mme Élodie Rousseau (TotalEnergies), contact elodie@total.fr"
        result = sf.anonymize(text, ner_detection=False)
        # regex couche 1 : toujours active
        assert "[EMAIL_0]" in result
        # PAS de détection fraîche : la personne et l'org restent lisibles
        assert "Mme Élodie Rousseau" in result and "TotalEnergies" in result
        assert ner_on.calls == 0

    def test_vault_first_still_masks_known_user_pii(self, ner_on, sf):
        """La PII que l'utilisateur a TAPÉE reste masquée partout — y compris
        quand elle réapparaît dans un résultat d'outil."""
        sf.anonymize("Je m'appelle Mme Élodie Rousseau.")          # texte user → détection
        result = sf.anonymize(
            "Résultat outil : dossier de Mme Élodie Rousseau trouvé (réf 81).",
            ner_detection=False,
        )
        assert "Élodie Rousseau" not in result
        assert "[PERSON_0]" in result


# ── Pin : allow-list des services intégrés ───────────────────────────────────

class TestServiceAllowlist:
    """« Vérifie mon dépôt GitHub » → [ORG_0] cassait le routage d'outils.
    Les noms des plateformes intégrées ne sont jamais masqués."""

    def test_github_never_masked_even_if_detected(self, monkeypatch, sf):
        monkeypatch.setenv("PII_NER_ENABLED", "1")
        fake = FakeGLiNERModel([("GitHub", "organization", 0.97),
                                ("TotalEnergies", "organization", 0.99)])
        monkeypatch.setattr(pii_ner, "_engine", PIINEREngine(fake))
        result = sf.anonymize("Compare mon dépôt GitHub avec celui de TotalEnergies.")
        assert "GitHub" in result                 # service : jamais masqué
        assert "TotalEnergies" not in result      # vraie org : masquée
        assert "[ORG_" in result

    def test_env_extension(self, monkeypatch):
        monkeypatch.setenv("PII_NER_ALLOWLIST", "MonServicePerso, AutreOutil")
        assert pii_ner.is_service_allowlisted("monserviceperso") is True
        assert pii_ner.is_service_allowlisted("Gmail") is True   # défauts conservés
        assert pii_ner.is_service_allowlisted("Capgemini") is False

    def test_exact_match_only(self):
        """« GitHub SARL » (vraie société) n'est PAS couverte par l'entrée
        « github » — match exact sur la valeur normalisée, pas de sous-chaîne."""
        assert pii_ner.is_service_allowlisted("GitHub") is True
        assert pii_ner.is_service_allowlisted("GitHub SARL") is False

    def test_polluted_vault_entry_heals(self, monkeypatch, sf):
        """Une entrée vault créée AVANT l'allow-list ([ORG_0]=GitHub) cesse
        d'être re-masquée : les conversations polluées guérissent."""
        monkeypatch.setenv("PII_NER_ENABLED", "1")
        monkeypatch.setattr(pii_ner, "_engine", PIINEREngine(FakeGLiNERModel([])))
        sf._vault["[ORG_0]"] = "GitHub"
        sf._counter = 1
        result = sf.anonymize("Regarde sur GitHub stp.")
        assert result == "Regarde sur GitHub stp."


# ── Pin de périmètre : la couche 2 ne gère QUE person/org/address ────────────

class TestLayerScope:
    def test_ner_labels_exclude_regex_territory(self):
        """email / téléphone / IBAN / CB appartiennent à la couche 1 regex
        (déterministe). Le bench a mesuré le NER détectant le MOT « mail »
        comme email (0.71) — exclure ces labels du NER élimine cette classe
        de faux positifs par construction. NE PAS ajouter ces labels ici."""
        assert pii_ner.NER_LABELS == ["person", "organization", "address"]
        assert pii_ner.LABEL_TO_PLACEHOLDER == {
            "person": "PERSON",
            "organization": "ORG",
            "address": "ADDRESS",
        }
        assert pii_ner.NER_PLACEHOLDER_LABELS == {"PERSON", "ORG", "ADDRESS"}


# ── Boot : fail-open quand le modèle ONNX est absent ─────────────────────────

class TestLoadFailOpen:
    def test_missing_model_dir_returns_false(self, monkeypatch, tmp_path):
        monkeypatch.setenv("PII_NER_ENABLED", "1")
        monkeypatch.setenv("PII_NER_MODEL_DIR", str(tmp_path / "nope"))
        monkeypatch.setattr(pii_ner, "_engine", None)
        assert load_ner_engine() is False
        assert pii_ner.get_ner_engine() is None

    def test_flag_off_never_loads(self, monkeypatch):
        monkeypatch.delenv("PII_NER_ENABLED", raising=False)
        monkeypatch.setattr(pii_ner, "_engine", None)
        assert load_ner_engine() is False
        assert pii_ner.get_ner_engine() is None

    def test_unload(self, monkeypatch, fake_model):
        monkeypatch.setattr(pii_ner, "_engine", PIINEREngine(fake_model))
        unload_ner_engine()
        assert pii_ner.get_ner_engine() is None
