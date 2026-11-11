"""v0.5 D6: the seller's company profile — preamble for every prompt, and spotting our speakers."""

import pytest

from app.llm.seller import (
    SellerProfile,
    get_seller_profile,
    is_our_speaker,
    seller_preamble,
    set_seller_profile,
    with_seller,
)


@pytest.fixture(autouse=True)
def _reset_profile():
    set_seller_profile(SellerProfile())
    yield
    set_seller_profile(SellerProfile())


def profile() -> SellerProfile:
    return SellerProfile(name="Acme Corp", aliases=["Acme", "AcmeCo"], email_domains=["acme.io"])


class TestPreamble:
    def test_empty_when_not_configured(self):
        assert seller_preamble(SellerProfile()) == ""
        assert with_seller("hello") == "hello"

    def test_names_the_seller_and_demands_exact_spelling(self):
        text = seller_preamble(profile())
        assert "Acme Corp" in text
        assert "exactly" in text.lower()
        assert "Acme" in text and "AcmeCo" in text  # aliases are listed as the same company

    def test_with_seller_prepends_to_any_prompt(self):
        set_seller_profile(profile())
        out = with_seller("Summarise this call.")
        assert out.startswith("The seller") or "Acme Corp" in out.split("\n")[0]
        assert out.endswith("Summarise this call.")

    def test_with_seller_is_idempotent(self):
        set_seller_profile(profile())
        once = with_seller("x")
        assert with_seller(once) == once


class TestOurSpeaker:
    def test_unconfigured_never_matches(self):
        assert is_our_speaker("Jordan from Acme Corp", profile=SellerProfile()) is False

    def test_matches_name_or_alias_in_the_label(self):
        p = profile()
        assert is_our_speaker("Jordan (Acme Corp)", profile=p)
        assert is_our_speaker("acme sales rep", profile=p)
        assert is_our_speaker("AcmeCo support", profile=p)

    def test_does_not_match_other_companies_or_substrings(self):
        p = profile()
        assert not is_our_speaker("Maria Lopez", profile=p)
        assert not is_our_speaker("Pacmeister Law Group", profile=p)  # 'acme' inside a word

    def test_matches_email_domain(self):
        p = profile()
        assert is_our_speaker("jordan@acme.io", profile=p)
        assert is_our_speaker("Jordan", email="jordan@acme.io", profile=p)
        assert is_our_speaker("Jordan", email="JORDAN@Sales.Acme.io", profile=p)  # subdomain
        assert not is_our_speaker("Maria", email="maria@client.com", profile=p)
        assert not is_our_speaker("Maria", email="maria@notacme.io", profile=p)


def test_profile_round_trips_through_dict():
    p = profile()
    assert SellerProfile.from_dict(p.to_dict()) == p
    assert SellerProfile.from_dict(None) == SellerProfile()
    assert SellerProfile.from_dict({"name": "  Acme  ", "aliases": [" a ", "", "a"], "email_domains": ["@Acme.IO "]}) == (
        SellerProfile(name="Acme", aliases=["a"], email_domains=["acme.io"])
    )


def test_get_seller_profile_returns_what_was_set():
    set_seller_profile(profile())
    assert get_seller_profile().name == "Acme Corp"


class TestInjectedIntoEveryPrompt:
    """The preamble must reach the model for both registered prompts and free-form generate()."""

    def test_registered_prompts_render_with_the_preamble(self):
        from app.llm.prompts import PROMPTS

        set_seller_profile(profile())
        for name, prompt in PROMPTS.items():
            # Fill every placeholder with a stub so each template renders.
            import string

            fields = {f for _, f, _, _ in string.Formatter().parse(prompt.template) if f}
            rendered = prompt.render({f: "x" for f in fields})
            assert "Acme Corp" in rendered.split("\n\n", 1)[0], name

    def test_unconfigured_registered_prompts_are_unchanged(self):
        import string

        from app.llm.prompts import PROMPTS

        prompt = PROMPTS["tagger"]
        fields = {f for _, f, _, _ in string.Formatter().parse(prompt.template) if f}
        assert prompt.render({f: "x" for f in fields}) == prompt.template.format(**{f: "x" for f in fields})

    @pytest.mark.asyncio
    async def test_openai_generate_sends_the_preamble(self):
        import json

        import httpx
        import respx
        from pydantic import BaseModel

        from app.llm.client import OpenAIResponsesClient

        class Out(BaseModel):
            answer: str = ""

        set_seller_profile(profile())
        client = OpenAIResponsesClient(api_key="test-key", base_url="https://llm.test/v1")
        try:
            with respx.mock:
                route = respx.post("https://llm.test/v1/responses").mock(
                    return_value=httpx.Response(
                        200,
                        json={
                            "id": "r1",
                            "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps({"answer": "ok"})}]}],
                        },
                    )
                )
                await client.generate("Summarise this call.", Out, model="default")
                sent = json.loads(route.calls[0].request.content)
        finally:
            await client.close()
        text = sent["input"][0]["content"]
        assert "Acme Corp" in text and text.endswith("Summarise this call.")
