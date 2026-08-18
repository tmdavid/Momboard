"""Settings management contract regressions."""

import pytest


@pytest.mark.asyncio
async def test_local_backend_reports_active_model_and_no_key_requirement(app, auth_client):
    settings = app.state.settings
    settings.llm_backend = "local"
    settings.llm_local_model = "qwen3:8b"
    settings.openai_api_key = ""

    response = await auth_client.get("/api/settings/status")

    assert response.status_code == 200
    llm = response.json()["llm"]
    assert llm["backend"] == "local"
    assert llm["model_normalizer"] == "qwen3:8b"
    assert llm["model_tagger"] == "qwen3:8b"
    assert llm["model_analyst"] == "qwen3:8b"
    assert llm["model_synthesizer"] == "qwen3:8b"
    assert llm["api_key_configured"] is False
    assert llm["api_key_hint"] == "not required"


@pytest.mark.asyncio
async def test_settings_status_reports_taxonomy_permission(auth_client, member_client):
    admin_response = await auth_client.get("/api/settings/status")
    member_response = await member_client.get("/api/settings/status")

    assert admin_response.status_code == 200
    assert member_response.status_code == 200
    assert admin_response.json()["can_manage_taxonomy"] is True
    assert member_response.json()["can_manage_taxonomy"] is False


@pytest.mark.asyncio
async def test_company_directory_includes_conversation_count(auth_client):
    created = await auth_client.post(
        "/api/companies",
        json={"name": "Directory Corp", "domain": "directory.example"},
    )
    assert created.status_code == 201

    response = await auth_client.get("/api/companies")

    assert response.status_code == 200
    company = next(item for item in response.json() if item["name"] == "Directory Corp")
    assert company["conversation_count"] == 0


@pytest.mark.asyncio
async def test_contact_creation_preserves_selected_company(auth_client):
    company_response = await auth_client.post(
        "/api/companies",
        json={"name": "Linked Corp", "domain": None},
    )
    assert company_response.status_code == 201
    company_id = company_response.json()["id"]

    response = await auth_client.post(
        "/api/contacts",
        json={
            "name": "Jane Example",
            "role": "Research lead",
            "email": "jane@example.test",
            "company_id": company_id,
        },
    )

    assert response.status_code == 201
    assert response.json()["company_id"] == company_id
