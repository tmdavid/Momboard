# M5 — Frontend (Library + Conversation)

Frontend tasks develop against MSW mocks of the OpenAPI contract; they do not block on M3/M4. TDD here = component/interaction tests in Vitest + Testing Library (RED), then components (GREEN). Visual fidelity comes from the prototypes — treat them as the design spec.

## T14 — SPA scaffold, API client, auth flow

**Depends on:** T04 (auth contract)

**RED** — `web/src/__tests__/auth.test.tsx`

```tsx
test("unauthenticated user sees login form, not the library", ...)
test("successful login stores nothing in localStorage (cookie only) and shows Library", ...)
test("401 from any API call redirects to login", ...)
```

**GREEN** — Vite + TS + Tailwind + TanStack Query scaffold under `web/`; typed API client generated from OpenAPI (`openapi-typescript`); `AuthGate` component; router with `/`, `/conversations/:id`, `/explore`, `/insights`. FastAPI serves `web/dist` as static fallback.

---

## T15 — Library page  *(prototype: `../prototypes/library.html`)*

**Depends on:** T14

**RED** — `web/src/__tests__/library.test.tsx`

```tsx
test("renders a row per conversation with date, company, contact, title", ...)
test("row shows tag chips with counts (⚡3 💰1) and critique score badge", ...)
test("processing conversations show a spinner status chip, not a score", ...)
test("filter by tag narrows the table (query param sent to API)", ...)
test("free-text search debounces 300ms then queries q=", ...)
test("empty state shows 'No conversations yet' with a New Conversation CTA", ...)
```

**GREEN** — `LibraryPage` per prototype: filter bar (tag multi-select chips, company select, date range, search), table, status chips, pagination. Server-side filtering only — no client-side filter logic beyond wiring params.

---

## T16 — New conversation modal  *(prototype: `../prototypes/library.html` — click “New conversation”)*

**Depends on:** T15

**RED**

```tsx
test("modal collects title, date, interviewer, company (combobox w/ create), contacts, meta fields", ...)
test("transcript accepts paste or .txt/.vtt file; format auto-detected label shown", ...)
test("submit POSTs and row appears optimistically with processing status", ...)
test("SSE updates flip the row to ready without reload (mock EventSource)", ...)
```

**GREEN** — modal per prototype; `useConversationEvents(id)` hook wrapping EventSource; optimistic insert via TanStack Query cache.

---

## T17 — Conversation page: transcript + review  *(prototype: `../prototypes/conversation.html`)*

**Depends on:** T14 (contract), T13 (review endpoints — mockable)

**RED** — `web/src/__tests__/conversation.test.tsx`

```tsx
test("utterances render in order, our-side vs their-side visually distinct", ...)
test("highlighted utterances show emoji chip; suggested ones look pending (dashed)", ...)
test("clicking a chip opens popover with accept / reject / edit tag", ...)
test("keyboard: j/k moves through suggested highlights, a accepts, x rejects", ...)
test("accepting fires PATCH and chip switches to solid immediately (optimistic)", ...)
test("analysis sidebar renders summary, pains w/ evidence links, commitments, critique score", ...)
test("clicking evidence link scrolls to and flashes the source utterance", ...)
test("select text in an utterance → 'add highlight' affordance → manual highlight POSTed", ...)
```

**GREEN** — three-pane layout per prototype; review-mode state machine as a hook (`useReviewQueue`); popover; critique card with violations list.

---

## T18 — Notes panel (the GDoc replacement)

**Depends on:** T17. Backend + frontend in one task.

**RED (backend)** — `tests/test_notes_api.py`

```python
@pytest.mark.asyncio
async def test_get_note_creates_empty_on_first_access(auth_client): ...
@pytest.mark.asyncio
async def test_put_note_upserts_markdown_and_bumps_updated_at(auth_client): ...
@pytest.mark.asyncio
async def test_put_with_stale_updated_at_returns_409(auth_client):
    # optimistic concurrency: client sends the updated_at it loaded
```

**RED (frontend)**

```tsx
test("notes panel toggles open, shows markdown editor + preview tabs", ...)
test("autosaves 1.5s after typing stops; shows saved/saving indicator", ...)
test("409 conflict shows 'someone else edited' banner with reload option", ...)
```

**GREEN** — `GET/PUT /api/conversations/{id}/note`; panel per prototype (bottom drawer), plain `<textarea>` + `marked` preview (no heavy editor dep).
