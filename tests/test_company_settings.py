"""v0.5 D6: 'Your company' in Settings — saved in the database, used by every prompt."""

import pytest
from httpx import AsyncClient

from app.llm.seller import SellerProfile, get_seller_profile, seller_preamble, set_seller_profile

PAYLOAD = {"name": "Acme Corp", "aliases": ["Acme", "AcmeCo"], "email_domains": ["acme.io"]}


@pytest.mark.asyncio
async def test_default_is_empty(auth_client: AsyncClient):
    r = await auth_client.get("/api/settings/company")
    assert r.status_code == 200
    assert r.json() == {"name": "", "aliases": [], "email_domains": [], "configured": False}


@pytest.mark.asyncio
async def test_admin_can_save_and_read_back(auth_client: AsyncClient):
    r = await auth_client.put("/api/settings/company", json=PAYLOAD)
    assert r.status_code == 200
    assert r.json() == {**PAYLOAD, "configured": True}
    again = await auth_client.get("/api/settings/company")
    assert again.json()["name"] == "Acme Corp" and again.json()["email_domains"] == ["acme.io"]


@pytest.mark.asyncio
async def test_saving_updates_the_live_profile_used_by_prompts(auth_client: AsyncClient):
    await auth_client.put("/api/settings/company", json=PAYLOAD)
    assert get_seller_profile().name == "Acme Corp"
    assert "Acme Corp" in seller_preamble()


@pytest.mark.asyncio
async def test_input_is_cleaned(auth_client: AsyncClient):
    r = await auth_client.put(
        "/api/settings/company",
        json={"name": "  Acme  ", "aliases": [" Acme ", "", "acme", "Ac"], "email_domains": ["@ACME.io ", "acme.io"]},
    )
    assert r.status_code == 200
    assert r.json()["name"] == "Acme"
    assert r.json()["aliases"] == ["Acme", "Ac"]  # blanks and case-insensitive duplicates removed
    assert r.json()["email_domains"] == ["acme.io"]  # lower-cased, '@' stripped, de-duplicated


@pytest.mark.asyncio
async def test_clearing_the_name_turns_it_off(auth_client: AsyncClient):
    await auth_client.put("/api/settings/company", json=PAYLOAD)
    r = await auth_client.put("/api/settings/company", json={"name": "", "aliases": [], "email_domains": []})
    assert r.json()["configured"] is False
    assert seller_preamble() == ""


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad",
    [
        {"name": "x" * 201, "aliases": [], "email_domains": []},
        {"name": "Acme", "aliases": ["a"] * 21, "email_domains": []},
        {"name": "Acme", "aliases": [], "email_domains": ["not a domain"]},
        {"name": "Acme", "aliases": [], "email_domains": ["a" * 300 + ".com"]},
    ],
)
async def test_invalid_input_is_rejected(auth_client: AsyncClient, bad):
    r = await auth_client.put("/api/settings/company", json=bad)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_member_can_read_but_not_change(member_client: AsyncClient):
    assert (await member_client.get("/api/settings/company")).status_code == 200
    assert (await member_client.put("/api/settings/company", json=PAYLOAD)).status_code == 403


@pytest.mark.asyncio
async def test_requires_login(client: AsyncClient):
    assert (await client.get("/api/settings/company")).status_code == 401
    assert (await client.put("/api/settings/company", json=PAYLOAD)).status_code == 401


@pytest.mark.asyncio
async def test_profile_survives_a_restart(auth_client: AsyncClient, session_factory):
    from app.services.seller_profile import refresh_seller_profile

    await auth_client.put("/api/settings/company", json=PAYLOAD)
    set_seller_profile(SellerProfile())  # simulate a fresh process
    async with session_factory() as db:
        profile = await refresh_seller_profile(db)
    assert profile.name == "Acme Corp" and get_seller_profile().aliases == ["Acme", "AcmeCo"]
