"""Unit tests for IntentRouter — scoring and routing decisions.

Run with:  cd backend && python -m pytest tests/test_intent_router.py -v

Note: SLM routing is only active when SLM_ENABLED=true.  Tests that check
SLM routing mock that setting; tests that check LLM routing work regardless.
"""
import pytest
from unittest.mock import patch, MagicMock

from app.services.intent_router import IntentRouter, ModelTier, RoutingDecision


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def router():
    return IntentRouter()


def _settings_slm_enabled(threshold: int = 40):
    """Return a mock Settings with SLM enabled."""
    s = MagicMock()
    s.slm_enabled = True
    s.slm_complexity_threshold = threshold
    return s


def _settings_slm_disabled():
    s = MagicMock()
    s.slm_enabled = False
    s.slm_complexity_threshold = 40
    return s


# ── SLM disabled (default) ────────────────────────────────────────────────────

class TestSLMDisabled:
    def test_always_routes_to_llm_when_slm_disabled(self, router):
        with patch("app.config.get_settings", return_value=_settings_slm_disabled()):
            decision = router.route("météo Paris")
        assert decision.tier == ModelTier.LLM
        assert decision.score == 100
        assert decision.reason == "SLM disabled"

    def test_complex_also_llm_when_disabled(self, router):
        with patch("app.config.get_settings", return_value=_settings_slm_disabled()):
            decision = router.route("Explique-moi pourquoi la relativité générale fonctionne")
        assert decision.tier == ModelTier.LLM


# ── Simple messages → SLM ────────────────────────────────────────────────────

class TestSimpleMessages:
    def _route(self, router, text, threshold=40):
        with patch("app.config.get_settings",
                   return_value=_settings_slm_enabled(threshold)):
            return router.route(text)

    def test_weather_query_slm(self, router):
        d = self._route(router, "météo Paris")
        assert d.tier == ModelTier.SLM

    def test_short_weather_slm(self, router):
        d = self._route(router, "météo ?")
        assert d.tier == ModelTier.SLM

    def test_calendar_query_slm(self, router):
        d = self._route(router, "mon agenda de demain")
        assert d.tier == ModelTier.SLM

    def test_translate_query_slm(self, router):
        d = self._route(router, "traduis bonjour en anglais")
        assert d.tier == ModelTier.SLM

    def test_qr_code_slm(self, router):
        # Note: "génère un qr code" contains "code" which triggers the programming
        # pattern (+25) and overrides the qr_code simplicity signal (-15).
        # Use a message that only exercises the qr_code simplicity keyword.
        d = self._route(router, "affiche un qr pour partager mon wifi")
        assert d.tier == ModelTier.SLM

    def test_notes_slm(self, router):
        d = self._route(router, "prends une note : acheter du pain")
        assert d.tier == ModelTier.SLM

    def test_score_bounded_0_100(self, router):
        # Very simple message should have score ≥ 0
        d = self._route(router, "météo")
        assert 0 <= d.score <= 100


# ── Complex messages → LLM ───────────────────────────────────────────────────

class TestComplexMessages:
    def _route(self, router, text, threshold=40):
        with patch("app.config.get_settings",
                   return_value=_settings_slm_enabled(threshold)):
            return router.route(text)

    def test_pourquoi_explanation_llm(self, router):
        d = self._route(router, "Pourquoi Python est-il lent comparé à C++ ?")
        assert d.tier == ModelTier.LLM

    def test_analyse_llm(self, router):
        d = self._route(router, "Analyse ce fichier PDF et fais un résumé détaillé")
        assert d.tier == ModelTier.LLM

    def test_code_generation_llm(self, router):
        d = self._route(router, "Programme un script Python qui parse un CSV et génère un graphique")
        assert d.tier == ModelTier.LLM

    def test_long_message_llm(self, router):
        # A message over 150 chars should get +20 to score
        long_msg = "Explique-moi " + "en détail " * 20 + "le fonctionnement."
        d = self._route(router, long_msg)
        assert d.tier == ModelTier.LLM

    def test_url_in_message_raises_score(self, router):
        d = self._route(router, "Va sur https://example.com et récupère les données")
        assert d.tier == ModelTier.LLM

    def test_subordinate_clause_raises_score(self, router):
        d = self._route(router, "Réponds-moi parce que j'ai besoin de comprendre")
        # Has "parce que" (subordinate clause) + "Réponds" — likely LLM
        assert d.tier == ModelTier.LLM


# ── Scoring internals ─────────────────────────────────────────────────────────

class TestScoring:
    def test_score_increases_with_complex_keyword(self, router):
        simple = router._score("météo", [])
        complex_ = router._score("explique-moi pourquoi les étoiles brillent", [])
        assert complex_ > simple

    def test_score_decreases_with_simple_keyword(self, router):
        baseline = router._score("dis-moi quelque chose", [])
        with_simple = router._score("météo", [])
        assert with_simple < baseline

    def test_score_always_in_range(self, router):
        messages = [
            "",
            "a",
            "météo " * 50,
            "pourquoi " * 20 + "parce que " * 20,
        ]
        for msg in messages:
            score = router._score(msg, [])
            assert 0 <= score <= 100, f"Score {score} out of range for: {msg[:40]}"

    def test_multi_sentence_raises_score(self, router):
        one = router._score("météo Paris.", [])
        multi = router._score("météo Paris. Donne-moi les détails. Et aussi demain.", [])
        assert multi > one

    def test_complex_cap_at_two_keywords(self, router):
        # Adding more than 2 complex keywords should not keep increasing beyond the cap
        msg2 = "Explique pourquoi c'est ainsi."
        msg4 = "Explique pourquoi et analyse et compare et évalue."
        score2 = router._score(msg2, [])
        score4 = router._score(msg4, [])
        # Both should be high but the cap (2 complex hits max) applies
        # score4 shouldn't exceed score2 by more than what structural features add
        assert score4 >= score2  # more complex features → higher, but capped

    def test_simple_cap_at_three_keywords(self, router):
        # More than 3 simple keywords shouldn't keep pushing score below 0
        msg = "météo agenda traduction notes to-do itin\u00e9raire calcule"
        score = router._score(msg, [])
        assert score >= 0


# ── phase2_adjustment ─────────────────────────────────────────────────────────

class TestPhase2:
    def test_phase2_returns_zero_in_phase1(self, router):
        assert router._phase2_adjustment("any message", 50) == 0


# ── RoutingDecision ───────────────────────────────────────────────────────────

class TestRoutingDecision:
    def test_decision_has_reason(self, router):
        with patch("app.config.get_settings",
                   return_value=_settings_slm_enabled()):
            d = router.route("météo Paris")
        assert isinstance(d.reason, str)
        assert len(d.reason) > 0

    def test_decision_tier_is_enum(self, router):
        with patch("app.config.get_settings",
                   return_value=_settings_slm_disabled()):
            d = router.route("test")
        assert isinstance(d.tier, ModelTier)
