# M1 — Schema, seed, auth

## T03 — Models + first real migration + tag seed

**Depends on:** T02

**RED** — `tests/test_schema.py`

```python
ALL_TABLES = {"companies","contacts","conversations","conversation_contacts",
              "utterances","tags","highlights","analyses","notes","users","jobs"}

def test_all_tables_exist_after_upgrade(migrated_engine):
    assert ALL_TABLES <= set(inspect(migrated_engine).get_table_names())

def test_pks_are_integer_autoincrement(migrated_engine):
    # every table's pk column is INTEGER, except tags.key (VARCHAR natural key)
    ...

@pytest.mark.asyncio
async def test_tag_seed_is_idempotent(db_session):
    from app.seed import seed_tags
    await seed_tags(db_session); await seed_tags(db_session)
    keys = {t.key for t in (await db_session.execute(select(Tag))).scalars()}
    assert {"pain","obstacle","workaround","emotion_pos","emotion_neg","context",
            "feature_request","money","person","followup","commitment","compliment"} <= keys
    assert (await db_session.scalar(select(func.count(Tag.key)))) == 12

@pytest.mark.asyncio
async def test_highlight_requires_valid_tag_key(db_session):
    with pytest.raises(IntegrityError): ...  # FK enforced (incl. on SQLite)
```

**GREEN**

- `app/models.py` per DESIGN.md §4: Integer autoincrement PKs (except `tags.key` string PK), `JSON().with_variant(JSONB, "postgresql")`, UTC datetimes with Python-side defaults, indexes on `conversations.happened_at`, `highlights(tag_key, status)`, `utterances(conversation_id, idx)`.
- One Alembic revision creating everything.
- `app/seed.py` with `seed_tags()` (upsert by key, from the §2 taxonomy incl. emoji/signal_strength/sort_order) + `python -m app.seed` entrypoint.

---

## T04 — Users + session auth

**Depends on:** T03

**RED** — `tests/test_auth.py`

```python
@pytest.mark.asyncio
async def test_login_wrong_password_401(client, user_david): ...

@pytest.mark.asyncio
async def test_login_sets_httponly_session_cookie_and_me_works(client, user_david):
    r = await client.post("/auth/login", json={"email": "d@rp.com", "password": "pw"})
    assert r.status_code == 200 and "session" in r.cookies
    assert (await client.get("/api/me")).json()["email"] == "d@rp.com"

@pytest.mark.asyncio
async def test_protected_route_401_without_cookie(client):
    assert (await client.get("/api/conversations")).status_code == 401

@pytest.mark.asyncio
async def test_admin_only_route_403_for_member(client, member_session): ...

def test_create_user_cli(tmp_db):
    # `python -m app.users create --email x --role admin` prompts/accepts password, hashes with argon2
    ...
```

**GREEN**

- argon2-cffi hashing; signed server-side session cookie (itsdangerous or starlette SessionMiddleware + server-side store table if you prefer revocation).
- `require_user` / `require_admin` dependencies; wire onto an (empty for now) `/api` router.
- User management CLI (no self-signup).

**Done when:** every subsequent `/api/*` route is behind `require_user` by router-level dependency, verified by test.
