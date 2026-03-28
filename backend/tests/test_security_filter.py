"""Unit tests for SecurityFilter — anonymize / deanonymize / is_critical.

Run with:  cd backend && python -m pytest tests/test_security_filter.py -v
"""
import pytest
from app.services.security_filter import SecurityFilter


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def sf():
    """Fresh SecurityFilter for each test."""
    return SecurityFilter()


# ── anonymize: basic detection ────────────────────────────────────────────────

class TestAnonymizeBasic:
    def test_email_replaced(self, sf):
        result = sf.anonymize("Contact me at alice@example.com please.")
        assert "alice@example.com" not in result
        assert "[EMAIL_0]" in result

    def test_phone_replaced(self, sf):
        result = sf.anonymize("Mon numéro est 06 12 34 56 78.")
        assert "06 12 34 56 78" not in result
        assert "[PHONE_" in result

    def test_card_replaced(self, sf):
        result = sf.anonymize("Carte : 4111 1111 1111 1111")
        assert "4111 1111 1111 1111" not in result
        assert "[CARD_" in result

    def test_iban_replaced(self, sf):
        result = sf.anonymize("IBAN : FR76 3000 6000 0112 3456 7890 189")
        assert "FR76" not in result
        assert "[IBAN_" in result

    def test_token_replaced(self, sf):
        result = sf.anonymize("api_key=sk-abc123XYZdef456789012345678901")
        assert "sk-abc123XYZdef456789012345678901" not in result
        assert "[TOKEN_" in result

    def test_no_false_positive_plain_text(self, sf):
        text = "Bonjour, comment vas-tu aujourd'hui ?"
        assert sf.anonymize(text) == text

    def test_empty_string(self, sf):
        assert sf.anonymize("") == ""


# ── anonymize: deduplication ──────────────────────────────────────────────────

class TestAnonymizeDeduplication:
    def test_same_email_same_placeholder(self, sf):
        r1 = sf.anonymize("Écris à bob@test.com")
        r2 = sf.anonymize("Réponds à bob@test.com aussi")
        # Same value → same placeholder across messages
        placeholder = next(k for k, v in sf._vault.items() if v == "bob@test.com")
        assert placeholder in r1
        assert placeholder in r2

    def test_same_value_twice_in_one_message(self, sf):
        result = sf.anonymize("De carol@x.com à carol@x.com")
        # Both occurrences should be replaced with the SAME placeholder
        assert result.count("[EMAIL_0]") == 2
        assert len(sf._vault) == 1  # only one entry in vault

    def test_different_emails_different_placeholders(self, sf):
        result = sf.anonymize("De a@x.com à b@x.com")
        assert "[EMAIL_0]" in result
        assert "[EMAIL_1]" in result
        assert len(sf._vault) == 2

    def test_counter_increments(self, sf):
        sf.anonymize("a@x.com")
        sf.anonymize("b@x.com")
        assert sf._counter == 2


# ── anonymize: position-based correctness ────────────────────────────────────

class TestAnonymizePositions:
    def test_pii_not_double_replaced(self, sf):
        """A PII value that is a substring of the placeholder must not be re-matched."""
        # EMAIL contains "@" which can't be part of a CARD — but let's test a
        # more subtle case: two different patterns that could overlap.
        result = sf.anonymize("token: abcdefghij1234567890ABCDE")
        # Should be replaced exactly once, not partially replaced twice
        assert result.count("[TOKEN_") == 1

    def test_surrounding_text_preserved(self, sf):
        result = sf.anonymize("Début alice@example.com fin")
        assert result.startswith("Début ")
        assert result.endswith(" fin")

    def test_multiple_pii_types_in_one_message(self, sf):
        text = "Email: test@x.com, tél: 06 01 02 03 04"
        result = sf.anonymize(text)
        assert "test@x.com" not in result
        assert "06 01 02 03 04" not in result
        assert len(sf._vault) == 2


# ── deanonymize ───────────────────────────────────────────────────────────────

class TestDeanonymize:
    def test_round_trip_email(self, sf):
        original = "Contacte bob@example.com pour info."
        anonymized = sf.anonymize(original)
        restored = sf.deanonymize(anonymized)
        assert restored == original

    def test_round_trip_phone(self, sf):
        original = "Appelle le 06 12 34 56 78 demain."
        assert sf.deanonymize(sf.anonymize(original)) == original

    def test_round_trip_multiple(self, sf):
        original = "De a@x.com vers b@x.com, carte 4111111111111111"
        assert sf.deanonymize(sf.anonymize(original)) == original

    def test_deanonymize_unknown_placeholder_unchanged(self, sf):
        text = "Résultat : [EMAIL_99] non mappé."
        assert sf.deanonymize(text) == text


# ── is_critical ───────────────────────────────────────────────────────────────

class TestIsCritical:
    def test_delete_keyword(self, sf):
        assert sf.is_critical("delete all files") is True

    def test_supprimer_keyword(self, sf):
        assert sf.is_critical("supprimer le dossier") is True

    def test_payment_keyword(self, sf):
        assert sf.is_critical("make a payment of 100€") is True

    def test_card_placeholder_is_critical(self, sf):
        assert sf.is_critical("charge [CARD_0] for 50€") is True

    def test_token_placeholder_is_critical(self, sf):
        assert sf.is_critical("use [TOKEN_2] to authenticate") is True

    def test_iban_placeholder_is_critical(self, sf):
        assert sf.is_critical("virer vers [IBAN_0]") is True

    def test_email_placeholder_not_critical(self, sf):
        # EMAIL placeholder alone should not trigger critical (no financial/destructive intent)
        assert sf.is_critical("send to [EMAIL_0]") is False

    def test_neutral_text_not_critical(self, sf):
        assert sf.is_critical("Quelle heure est-il ?") is False

    def test_case_insensitive(self, sf):
        assert sf.is_critical("DELETE FROM users") is True


# ── reset ─────────────────────────────────────────────────────────────────────

class TestReset:
    def test_reset_clears_vault(self, sf):
        sf.anonymize("user@test.com")
        assert len(sf._vault) > 0
        sf.reset()
        assert sf._vault == {}
        assert sf._counter == 0

    def test_reset_allows_fresh_numbering(self, sf):
        sf.anonymize("a@x.com")
        sf.reset()
        result = sf.anonymize("b@x.com")
        assert "[EMAIL_0]" in result  # counter restarted


# ── Edge cases ────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_redos_guard_truncates(self, sf):
        long_text = "a" * 100_000
        result = sf.anonymize(long_text)
        assert len(result) <= 50_000

    def test_no_mutation_of_input(self, sf):
        text = "user@example.com"
        original_text = text
        sf.anonymize(text)
        assert text == original_text
