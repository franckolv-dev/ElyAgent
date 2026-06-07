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
        # Digit-only form (legacy support).
        result = sf.anonymize("Mon numéro est 0612345678.")
        assert "0612345678" not in result
        assert "[PHONE_" in result

    @pytest.mark.parametrize("phone", [
        "06 12 34 56 78",          # spaces — the standard French written form
        "06.12.34.56.78",          # dots
        "06-12-34-56-78",          # dashes
        "0612345678",              # digits-only (legacy)
        "+33612345678",            # +33 digits-only
        "+33 6 12 34 56 78",       # +33 with spaces
        "+33-6-12-34-56-78",       # +33 with dashes
        "05 53 98 22 57",          # real value from a prospection mission
        "07 88 11 15 77",          # ditto
    ])
    def test_phone_french_formats(self, sf, phone):
        """Tels lifted from the web come with separators (the standard French
        written form). The old pattern accepted digits-only and missed them all
        — phones leaked to the LLM in clear. Pin every variant we want covered."""
        result = sf.anonymize(f"Tel: {phone}, contact me.")
        assert phone not in result, f"phone {phone!r} not anonymized"
        assert "[PHONE_" in result

    @pytest.mark.parametrize("text", [
        "Date 2024 12 15 10 30 47",   # date+time, no leading 0[1-9]
        "9 rue du 12 mai 2024 75001", # address — must not match
        "0612345",                    # too short
        "06123456789012",             # too long (10 digit prefix + more)
        "0012345678",                 # 00 — not a French mobile/landline
    ])
    def test_phone_no_false_positives(self, sf, text):
        result = sf.anonymize(text)
        assert "[PHONE_" not in result, f"false positive on {text!r}: {result!r}"

    def test_card_replaced(self, sf):
        result = sf.anonymize("Carte : 4111 1111 1111 1111")
        assert "4111 1111 1111 1111" not in result
        assert "[CARD_" in result

    def test_iban_replaced(self, sf):
        # Regex was tightened for ReDoS: spaces must be stripped before matching
        result = sf.anonymize("IBAN : FR7630006000011234567890189")
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
        result = sf.anonymize("De carol@example.com à carol@example.com")
        # Both occurrences should be replaced with the SAME placeholder
        assert result.count("[EMAIL_0]") == 2
        assert len(sf._vault) == 1  # only one entry in vault

    def test_different_emails_different_placeholders(self, sf):
        result = sf.anonymize("De alice@example.com à bob@example.com")
        assert "[EMAIL_0]" in result
        assert "[EMAIL_1]" in result
        assert len(sf._vault) == 2

    def test_counter_increments(self, sf):
        sf.anonymize("alice@example.com")
        sf.anonymize("bob@example.com")
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
        text = "Email: test@example.com, tél: 0601020304"
        result = sf.anonymize(text)
        assert "test@example.com" not in result
        assert "0601020304" not in result
        assert len(sf._vault) == 2


# ── deanonymize ───────────────────────────────────────────────────────────────

class TestDeanonymize:
    def test_round_trip_email(self, sf):
        original = "Contacte bob@example.com pour info."
        anonymized = sf.anonymize(original)
        restored = sf.deanonymize(anonymized)
        assert restored == original

    def test_round_trip_phone(self, sf):
        original = "Appelle le 0612345678 demain."
        assert sf.deanonymize(sf.anonymize(original)) == original

    def test_round_trip_multiple(self, sf):
        original = "De alice@example.com vers bob@example.com, carte 4111111111111111"
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
        sf.anonymize("alice@example.com")
        sf.reset()
        result = sf.anonymize("bob@example.com")
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
