"""API tokens (MCP PRD): generation, hashing, verification, expiry, revoke, limits."""

import base64
import re
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text

from app.models import ApiToken
from app.services import api_tokens as svc


async def make(db, user, **kw):
    kw.setdefault("name", "Claude")
    kw.setdefault("scope", "read")
    kw.setdefault("expires_in_days", 90)
    return await svc.create_token(db, user, **kw)


class TestFormat:
    def test_token_is_mb_plus_32_random_bytes_base64url(self):
        t = svc.generate_token()
        assert t.startswith("mb_") and len(t) == 46
        body = t[3:]
        assert re.fullmatch(r"[A-Za-z0-9_-]{43}", body)
        assert len(base64.urlsafe_b64decode(body + "=")) == 32

    def test_tokens_are_unique(self):
        assert len({svc.generate_token() for _ in range(200)}) == 200

    def test_hash_is_sha256_hex_and_deterministic(self):
        h = svc.hash_token("mb_abc")
        assert re.fullmatch(r"[0-9a-f]{64}", h) and h == svc.hash_token("mb_abc") and h != svc.hash_token("mb_abd")


@pytest.mark.asyncio
class TestCreate:
    async def test_stores_only_the_hash_and_an_eight_char_prefix(self, session_factory, user_david):
        async with session_factory() as db:
            row, plain = await make(db, user_david)
            await db.commit()
            assert row.token_hash == svc.hash_token(plain) and row.prefix == plain[:8]
            assert plain not in {row.token_hash, row.prefix, row.name}
            dump = " ".join(str(v) for v in row.__dict__.values())
            assert plain not in dump                        # the secret is not on the row at all

    async def test_read_scope_and_write_scope_which_implies_read(self, session_factory, user_david):
        async with session_factory() as db:
            r, _ = await make(db, user_david, scope="read")
            w, _ = await make(db, user_david, scope="write")
            assert r.scopes == ["read"] and w.scopes == ["read", "write"]
            assert svc.has_scope(r, "read") and not svc.has_scope(r, "write")
            assert svc.has_scope(w, "read") and svc.has_scope(w, "write")

    @pytest.mark.parametrize("days", [30, 90, 365])
    async def test_expiry_choices(self, session_factory, user_david, days):
        async with session_factory() as db:
            row, _ = await make(db, user_david, expires_in_days=days)
            delta = svc._aware(row.expires_at) - datetime.now(UTC)
            assert timedelta(days=days) - timedelta(minutes=1) < delta <= timedelta(days=days)

    async def test_never_expires(self, session_factory, user_david):
        async with session_factory() as db:
            row, _ = await make(db, user_david, expires_in_days=None)
            assert row.expires_at is None

    @pytest.mark.parametrize("kw", [{"name": ""}, {"name": "   "}, {"name": "x" * 101}, {"scope": "admin"},
                                     {"scope": ""}, {"expires_in_days": 7}, {"expires_in_days": 0}])
    async def test_invalid_input_is_rejected(self, session_factory, user_david, kw):
        async with session_factory() as db:
            with pytest.raises(svc.TokenError):
                await make(db, user_david, **kw)

    async def test_ten_active_tokens_per_user_then_refused(self, session_factory, user_david):
        async with session_factory() as db:
            made = [await make(db, user_david, name=f"t{i}") for i in range(10)]
            with pytest.raises(svc.TokenLimitError):
                await make(db, user_david, name="eleventh")
            # revoking one frees a slot; inactive tokens do not count
            await svc.revoke_token(db, made[0][0])
            await make(db, user_david, name="eleventh")

    async def test_the_limit_is_per_user(self, session_factory, user_david, user_member):
        async with session_factory() as db:
            for i in range(10):
                await make(db, user_david, name=f"t{i}")
            await make(db, user_member)                      # someone else is unaffected


@pytest.mark.asyncio
class TestVerify:
    async def test_a_valid_token_resolves_to_its_user(self, session_factory, user_david):
        async with session_factory() as db:
            _, plain = await make(db, user_david)
            await db.commit()
        async with session_factory() as db:
            v = await svc.verify_token(db, plain)
            assert v is not None and v.user.id == user_david.id and v.token.prefix == plain[:8]

    @pytest.mark.parametrize("bad", ["", "mb_", "nope", "mb_" + "a" * 43, "Bearer x", "mb_\x00", None])
    async def test_garbage_and_unknown_tokens_are_refused(self, session_factory, user_david, bad):
        async with session_factory() as db:
            await make(db, user_david)
            await db.commit()
        async with session_factory() as db:
            assert await svc.verify_token(db, bad) is None

    async def test_a_revoked_token_stops_working_immediately(self, session_factory, user_david):
        async with session_factory() as db:
            row, plain = await make(db, user_david)
            await db.commit()
            assert await svc.verify_token(db, plain) is not None
            await svc.revoke_token(db, row)
            await db.commit()
        async with session_factory() as db:
            assert await svc.verify_token(db, plain) is None

    async def test_an_expired_token_is_refused(self, session_factory, user_david):
        async with session_factory() as db:
            row, plain = await make(db, user_david)
            row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await db.commit()
        async with session_factory() as db:
            assert await svc.verify_token(db, plain) is None

    async def test_a_token_whose_user_was_deleted_is_refused(self, session_factory, user_member):
        async with session_factory() as db:
            _, plain = await make(db, user_member)
            await db.commit()
        async with session_factory() as db:
            # The foreign key normally stops this (revoke first); switch it off to simulate an orphan row.
            await db.execute(text("PRAGMA foreign_keys=OFF"))
            await db.execute(text("DELETE FROM users WHERE id = :i"), {"i": user_member.id})
            await db.commit()
        async with session_factory() as db:
            assert await svc.verify_token(db, plain) is None

    async def test_lookup_is_by_hash_and_compared_in_constant_time(self, session_factory, user_david, monkeypatch):
        calls = []
        real = svc.hmac.compare_digest
        monkeypatch.setattr(svc.hmac, "compare_digest", lambda a, b: (calls.append(1), real(a, b))[1])
        async with session_factory() as db:
            _, plain = await make(db, user_david)
            await db.commit()
        async with session_factory() as db:
            assert await svc.verify_token(db, plain) is not None
        assert calls, "verification must use hmac.compare_digest"

    async def test_last_used_is_updated_at_most_once_a_minute(self, session_factory, user_david):
        async with session_factory() as db:
            row, plain = await make(db, user_david)
            await db.commit()
            tid = row.id
        async with session_factory() as db:
            await svc.verify_token(db, plain)
            await db.commit()
        async with session_factory() as db:
            first = (await db.get(ApiToken, tid)).last_used_at
            assert first is not None
            await svc.verify_token(db, plain)
            await db.commit()
        async with session_factory() as db:
            assert (await db.get(ApiToken, tid)).last_used_at == first         # within the minute: untouched
            tok = await db.get(ApiToken, tid)
            tok.last_used_at = datetime.now(UTC) - timedelta(minutes=2)
            await db.commit()
        async with session_factory() as db:
            await svc.verify_token(db, plain)
            await db.commit()
        async with session_factory() as db:
            assert svc._aware((await db.get(ApiToken, tid)).last_used_at) > datetime.now(UTC) - timedelta(seconds=30)


@pytest.mark.asyncio
class TestListing:
    async def test_members_see_their_own_admins_see_all(self, session_factory, user_david, user_member):
        async with session_factory() as db:
            await make(db, user_david, name="admins")
            await make(db, user_member, name="members")
            await db.commit()
        async with session_factory() as db:
            assert [t.name for t in await svc.list_tokens(db, user_member)] == ["members"]
            assert sorted(t.name for t in await svc.list_tokens(db, user_david)) == ["admins", "members"]

    async def test_revoking_keeps_the_row_for_the_audit_trail(self, session_factory, user_david):
        async with session_factory() as db:
            row, _ = await make(db, user_david)
            await svc.revoke_token(db, row)
            await db.commit()
        async with session_factory() as db:
            rows = (await db.execute(select(ApiToken))).scalars().all()
            assert len(rows) == 1 and rows[0].revoked_at is not None

    async def test_revoking_twice_keeps_the_first_time(self, session_factory, user_david):
        async with session_factory() as db:
            row, _ = await make(db, user_david)
            await svc.revoke_token(db, row)
            first = row.revoked_at
            await svc.revoke_token(db, row)
            assert row.revoked_at == first

    def test_status_is_active_expired_or_revoked(self):
        now = datetime.now(UTC)
        t = ApiToken(revoked_at=None, expires_at=None)
        assert svc.token_status(t) == "active"
        assert svc.token_status(ApiToken(revoked_at=now, expires_at=None)) == "revoked"
        assert svc.token_status(ApiToken(revoked_at=None, expires_at=now - timedelta(days=1))) == "expired"
        assert svc.token_status(ApiToken(revoked_at=now, expires_at=now - timedelta(days=1))) == "revoked"
