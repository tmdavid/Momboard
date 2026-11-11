"""v0.5 U5: a light summary of one call for the Library preview panel."""

import pytest
from httpx import AsyncClient

from app.models import Analysis, Company, Conversation, Highlight, Utterance
from app.seed import seed_tags


async def make(db, *, analysis=None, status="ready", with_company=True):
    await seed_tags(db)
    co = None
    if with_company:
        co = Company(name="Pierce Law Group")
        db.add(co)
        await db.flush()
    c = Conversation(title="Pilot discussion", company_id=co.id if co else None, status=status, source="upload",
                     raw_transcript="x", transcript_format="name_colon")
    db.add(c)
    await db.flush()
    u = Utterance(conversation_id=c.id, idx=0, speaker_label="Pat", speaker_side="them", text="We need a pilot first.")
    db.add(u)
    await db.flush()
    if analysis is not None:
        db.add(Analysis(conversation_id=c.id, kind="conversation", result=analysis))
    await db.flush()
    return c, u


ANALYSIS = {
    "summary": "They want a pilot before an annual contract.",
    "top_pains": [
        {"pain": "Manual takedown review eats a day a week", "evidence_highlight_ids": [1], "severity": "high"},
        {"pain": "No way to prove coverage to clients", "evidence_highlight_ids": [], "severity": "medium"},
        {"pain": "Three people maintain the spreadsheet", "evidence_highlight_ids": [], "severity": "low"},
        {"pain": "A fourth pain that should be cut", "evidence_highlight_ids": [], "severity": "low"},
    ],
    "suggested_followups": ["Send the pilot proposal", "Intro to their partner"],
    "mom_test_critique": {"score": 7, "good_questions": [], "violations": []},
}


@pytest.mark.asyncio
async def test_preview_returns_the_summary_pains_score_and_followups(auth_client: AsyncClient, session_factory):
    async with session_factory() as db:
        c, _ = await make(db, analysis=ANALYSIS)
        await db.commit()
        cid = c.id
    r = await auth_client.get(f"/api/conversations/{cid}/preview")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == cid and body["title"] == "Pilot discussion" and body["company_name"] == "Pierce Law Group"
    assert body["summary"] == "They want a pilot before an annual contract."
    assert [p["pain"] for p in body["top_pains"]] == [
        "Manual takedown review eats a day a week", "No way to prove coverage to clients", "Three people maintain the spreadsheet"]
    assert body["top_pains"][0]["severity"] == "high"
    assert body["score"] == 7
    assert body["followups"] == ["Send the pilot proposal", "Intro to their partner"]


@pytest.mark.asyncio
async def test_preview_counts_only_suggestions_that_still_need_review(auth_client: AsyncClient, session_factory):
    async with session_factory() as db:
        c, u = await make(db, analysis=ANALYSIS)
        def hl(status, tag="pain", conf=0.9, quote="a"):
            return Highlight(conversation_id=c.id, utterance_id=u.id, tag_key=tag, quote=quote, status=status, origin="ai", confidence=conf)
        db.add_all([hl("suggested", quote="needs review one"), hl("suggested", tag="money", quote="needs review two"),
                    hl("suggested", conf=0.1, quote="below the pain floor"),    # hidden everywhere else, still review work
                    hl("accepted", quote="done"), hl("rejected", quote="done too")])
        await db.commit()
        cid = c.id
    body = (await auth_client.get(f"/api/conversations/{cid}/preview")).json()
    assert body["suggestions_to_review"] == 3     # review is where low-confidence guesses get judged


@pytest.mark.asyncio
async def test_preview_without_an_analysis_is_still_valid(auth_client: AsyncClient, session_factory):
    async with session_factory() as db:
        c, _ = await make(db, analysis=None, with_company=False)
        await db.commit()
        cid = c.id
    body = (await auth_client.get(f"/api/conversations/{cid}/preview")).json()
    assert body["summary"] is None and body["top_pains"] == [] and body["score"] is None and body["followups"] == []
    assert body["company_name"] is None and body["suggestions_to_review"] == 0


@pytest.mark.asyncio
async def test_preview_tolerates_a_malformed_analysis(auth_client: AsyncClient, session_factory):
    async with session_factory() as db:
        c, _ = await make(db, analysis={"summary": 5, "top_pains": "oops", "suggested_followups": [3, "ok"], "mom_test_critique": "x"})
        await db.commit()
        cid = c.id
    r = await auth_client.get(f"/api/conversations/{cid}/preview")
    assert r.status_code == 200
    body = r.json()
    assert body["summary"] is None and body["top_pains"] == [] and body["followups"] == ["ok"] and body["score"] is None


@pytest.mark.asyncio
async def test_preview_404_and_auth(auth_client: AsyncClient, client: AsyncClient):
    assert (await auth_client.get("/api/conversations/99999/preview")).status_code == 404
    assert (await client.get("/api/conversations/1/preview")).status_code == 401
