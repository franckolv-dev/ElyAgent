# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_security_audit_pile_a.py
# @brief      Pins des correctifs « pile A » de l'audit sécurité du 13/06 :
#             H1 (IDOR ban_action), M2 (PII : pas de troncature silencieuse),
#             M3 (vault vide vérifiable).
# @license    Elastic License 2.0
# =============================================================================
"""Run with:  cd backend && python -m pytest tests/test_security_audit_pile_a.py -v"""
from __future__ import annotations

import inspect
import uuid

import pytest
import pytest_asyncio


# ── H1 — ban_action n'accepte plus user_id/description du body (IDOR) ─────────


def test_ban_action_drops_user_controlled_body_params():
    from app.routers.validation import ban_action
    params = set(inspect.signature(ban_action).parameters)
    # Le contrat public ne doit PLUS exposer ces deux champs : ils
    # permettaient de viser l'identité d'un autre utilisateur.
    assert "user_id" not in params
    assert "description" not in params
    # Le reste du contrat est inchangé.
    assert {"action_id", "reason"} <= params


# ── M2 — anonymize traite > 50k SANS jeter le reste ──────────────────────────


class TestPiiNoSilentTruncation:
    def test_long_text_beyond_limit_is_not_dropped(self):
        from app.services.security_filter import SecurityFilter, _MAX_REGEX_INPUT
        sf = SecurityFilter()
        # PII placée APRÈS le plafond regex : avant le fix, ce bloc était
        # purement supprimé (le log prétendait « non anonymisé »).
        filler = "x" * (_MAX_REGEX_INPUT + 5_000)
        text = f"{filler} contact@example.com fin du document."
        out = sf.anonymize(text, ner_detection=False)
        # 1) Rien n'est jeté : la fin du document survit.
        assert "fin du document." in out
        assert len(out) > _MAX_REGEX_INPUT
        # 2) Et la PII au-delà du plafond EST masquée (traitée par blocs).
        assert "contact@example.com" not in out
        assert "[EMAIL_" in out

    def test_pii_before_and_after_limit_share_one_placeholder(self):
        from app.services.security_filter import SecurityFilter, _MAX_REGEX_INPUT
        sf = SecurityFilter()
        # Le MÊME email avant et après la frontière → même placeholder
        # (vault partagé entre blocs).
        email = "jean@example.com"
        text = f"{email} " + ("y" * _MAX_REGEX_INPUT) + f" {email}"
        out = sf.anonymize(text, ner_detection=False)
        assert email not in out
        assert out.count("[EMAIL_0]") == 2

    def test_short_text_unchanged_path_still_works(self):
        from app.services.security_filter import SecurityFilter
        sf = SecurityFilter()
        out = sf.anonymize("IBAN FR7630006000011234567890189 ok", ner_detection=False)
        assert "FR7630006000011234567890189" not in out
        assert "[IBAN_" in out


# ── M3 — un vault vide refuse un mauvais mot de passe ─────────────────────────


@pytest_asyncio.fixture(autouse=True)
async def _db():
    from app.database import init_db
    await init_db()


async def _make_user(uid: str) -> None:
    from app.database import async_session
    from app.models.user import User
    # uid complet, PAS de troncature : uid[:8] == "vault-XX" ne gardait que
    # 2 hex de l'uuid (256 valeurs) or username/email sont UNIQUE et la DB
    # locale persiste entre les runs → collisions aléatoires (flake 19/07).
    async with async_session() as db:
        db.add(User(id=uid, username=f"u_{uid}",
                    email=f"{uid}@t.local", hashed_password="x"))
        await db.commit()


class TestVaultEmptyVerifier:
    @pytest.mark.asyncio
    async def test_empty_vault_rejects_wrong_password(self):
        from app.services.vault_service import VaultService
        svc = VaultService()
        uid = f"vault-{uuid.uuid4().hex[:8]}"
        await _make_user(uid)

        # 1er unlock = init du vault (pose la sentinelle), vault VIDE.
        assert await svc.unlock_vault(uid, "correct-horse-battery") is True
        await svc.lock_vault(uid)

        # Cœur du bug M3 : sur un vault VIDE, un mauvais mdp doit être REFUSÉ
        # (avant le fix, il n'y avait rien à déchiffrer → tout passait).
        assert await svc.unlock_vault(uid, "WRONG-password") is False

        # Le bon mot de passe rouvre toujours.
        assert await svc.unlock_vault(uid, "correct-horse-battery") is True

    @pytest.mark.asyncio
    async def test_verifier_persisted_at_init(self):
        from app.database import async_session
        from app.models.vault import VaultConfig
        from app.services.vault_service import VaultService
        svc = VaultService()
        uid = f"vault-{uuid.uuid4().hex[:8]}"
        await _make_user(uid)
        await svc.unlock_vault(uid, "pw-init")

        async with async_session() as db:
            cfg = await db.get(VaultConfig, uid)
        assert cfg is not None
        assert cfg.verifier is not None and cfg.verifier_nonce is not None
