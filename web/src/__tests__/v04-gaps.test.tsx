/**
 * v0.4 gap closers:
 *  - Decisions UI uses the P1/P2 API (owner/area, draft, edit, quotes, search, sort,
 *    linked hypothesis + archived warning, superseded-by)
 *  - Hypotheses: archived section with Restore; the board pages through every result
 */
import { describe, test, expect } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { server } from '../test/mocks/server';
import { renderWithProviders } from '../test/render';
import { DecisionsPage } from '../pages/DecisionsPage';
import { HypothesesPage } from '../pages/HypothesesPage';

const decisionItem = (over: Record<string, unknown> = {}) => ({
  id: 1,
  title: 'Build auto-reports',
  status: 'decided',
  integrity: 'ok',
  integrity_checked_at: null,
  owner_id: 1,
  area: 'Reporting',
  decided_at: '2026-08-10T00:00:00Z',
  created_at: '2026-08-01T00:00:00Z',
  evidence_count: 2,
  hypothesis_id: 5,
  hypothesis_archived: false,
  ...over,
});

const detailBody = (over: Record<string, unknown> = {}) => ({
  id: 1,
  title: 'Build auto-reports',
  rationale_md: 'Weekly manual pain.',
  status: 'decided',
  integrity: 'ok',
  integrity_reasons: null,
  hypothesis_id: 5,
  hypothesis: { id: 5, statement: 'Teams export weekly to Excel', band: 'grounded', archived: false },
  owner_id: 1,
  area: 'Reporting',
  decided_at: '2026-08-10T00:00:00Z',
  decided_by: 1,
  superseded_by: null,
  superseded_by_title: null,
  evidence: [
    { highlight_id: 11, quote: 'We export every Monday', tag_key: 'pain', conversation_id: 1, conversation_title: 'Call A', conversation_happened_at: null, status: 'accepted' },
    { highlight_id: 12, quote: 'It takes six hours', tag_key: 'pain', conversation_id: 2, conversation_title: 'Call B', conversation_happened_at: null, status: 'accepted' },
  ],
  created_at: '2026-08-01T00:00:00Z',
  ...over,
});

function useDecisions(listItems = [decisionItem()], detail = detailBody()) {
  server.use(
    http.get('/api/decisions', () => HttpResponse.json({ items: listItems, total: listItems.length })),
    http.get('/api/decisions/:id', ({ params }) =>
      HttpResponse.json({ ...detail, id: Number(params.id), title: listItems.find((i) => i.id === Number(params.id))?.title ?? detail.title }),
    ),
  );
}

describe('Decisions page: P1/P2 backend features in the UI', () => {
  test('rows show owner name, area, quote count; archived belief is flagged', async () => {
    useDecisions([decisionItem({ hypothesis_archived: true }), decisionItem({ id: 2, title: 'Plain one', owner_id: null, area: null, evidence_count: 1, hypothesis_id: null })]);
    renderWithProviders(<DecisionsPage />);
    const row = (await screen.findByText('Build auto-reports')).closest('[role="button"]') as HTMLElement;
    await waitFor(() => expect(within(row).getByText(/David · Reporting/)).toBeInTheDocument());
    expect(within(row).getByText('2 quotes')).toBeInTheDocument();
    expect(within(row).getByText(/belief archived/i)).toBeInTheDocument();
    const plain = screen.getByText('Plain one').closest('[role="button"]') as HTMLElement;
    expect(within(plain).getByText('1 quote')).toBeInTheDocument();
    expect(within(plain).queryByText(/belief archived/i)).not.toBeInTheDocument();
  });

  test('search and sort are sent to the server', async () => {
    const seen: string[] = [];
    server.use(
      http.get('/api/decisions', ({ request }) => {
        seen.push(new URL(request.url).search);
        return HttpResponse.json({ items: [decisionItem()], total: 1 });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<DecisionsPage />);
    await screen.findByText('Build auto-reports');
    await user.type(screen.getByLabelText(/search decisions/i), 'pricing');
    await user.selectOptions(screen.getByLabelText(/sort decisions/i), 'integrity');
    await waitFor(() => {
      const last = new URLSearchParams(seen[seen.length - 1]);
      expect(last.get('q')).toBe('pricing');
      expect(last.get('sort')).toBe('integrity');
    });
  });

  test('empty search result says nothing matches (not "no decisions yet")', async () => {
    server.use(
      http.get('/api/decisions', ({ request }) =>
        HttpResponse.json({ items: new URL(request.url).searchParams.get('q') ? [] : [decisionItem()], total: 0 }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<DecisionsPage />);
    await screen.findByText('Build auto-reports');
    await user.type(screen.getByLabelText(/search decisions/i), 'zzz');
    expect(await screen.findByText(/no decisions match/i)).toBeInTheDocument();
  });

  test('detail shows owner/area, the linked hypothesis with band, and the archived warning', async () => {
    useDecisions([decisionItem()], detailBody({ hypothesis: { id: 5, statement: 'Teams export weekly to Excel', band: 'grounded', archived: true } }));
    const user = userEvent.setup();
    renderWithProviders(<DecisionsPage />);
    await user.click(await screen.findByText('Build auto-reports'));
    const box = await screen.findByTestId('linked-hypothesis-box');
    expect(within(box).getByText(/Teams export weekly to Excel/)).toBeInTheDocument();
    expect(within(box).getByText('Grounded')).toBeInTheDocument();
    expect(within(box).getByRole('alert')).toHaveTextContent(/this belief has been archived/i);
    expect(await screen.findByTestId('owner-area')).toHaveTextContent('Owner: David · Area: Reporting');
  });

  test('no archived warning when the hypothesis is active', async () => {
    useDecisions();
    const user = userEvent.setup();
    renderWithProviders(<DecisionsPage />);
    await user.click(await screen.findByText('Build auto-reports'));
    const box = await screen.findByTestId('linked-hypothesis-box');
    expect(within(box).queryByRole('alert')).not.toBeInTheDocument();
  });

  test('"Superseded by" shows the successor title and opens it', async () => {
    useDecisions(
      [decisionItem({ status: 'superseded' }), decisionItem({ id: 7, title: 'Successor plan' })],
      detailBody({ status: 'superseded', superseded_by: 7, superseded_by_title: 'Successor plan' }),
    );
    const user = userEvent.setup();
    renderWithProviders(<DecisionsPage />);
    await user.click(await screen.findByText('Build auto-reports'));
    const detail = await screen.findByRole('region', { name: /selected decision/i });
    await user.click(within(detail).getByRole('button', { name: 'Successor plan' }));
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Successor plan' })).toBeInTheDocument());
  });

  test('Edit saves title, rationale, owner and area via PATCH', async () => {
    let body: Record<string, unknown> | null = null;
    useDecisions();
    server.use(
      http.patch('/api/decisions/:id', async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(detailBody());
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<DecisionsPage />);
    await user.click(await screen.findByText('Build auto-reports'));
    await user.click(await screen.findByRole('button', { name: /^edit$/i }));
    const form = screen.getByRole('form', { name: /edit decision/i });
    await waitFor(() => expect(within(form).getByRole('option', { name: 'Maria' })).toBeInTheDocument());
    const title = within(form).getByLabelText(/^title$/i);
    await user.clear(title);
    await user.type(title, 'Build scheduled reports');
    await user.selectOptions(within(form).getByLabelText(/^owner$/i), '2');
    const area = within(form).getByLabelText(/^area$/i);
    await user.clear(area);
    await user.type(area, 'Insights');
    await user.click(within(form).getByRole('button', { name: /save changes/i }));
    await waitFor(() => expect(body).not.toBeNull());
    expect(body).toEqual({ title: 'Build scheduled reports', rationale_md: 'Weekly manual pain.', owner_id: 2, area: 'Insights' });
  });

  test('a quote can be removed, but not the last one on a non-draft decision', async () => {
    const deleted: string[] = [];
    useDecisions();
    server.use(
      http.delete('/api/decisions/:id/evidence/:hid', ({ params }) => {
        deleted.push(String(params.hid));
        return HttpResponse.json(detailBody());
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<DecisionsPage />);
    await user.click(await screen.findByText('Build auto-reports'));
    await user.click(await screen.findByRole('button', { name: /remove quote: we export every monday/i }));
    await waitFor(() => expect(deleted).toEqual(['11']));
  });

  test('no Remove offered when only one quote is cited (non-draft)', async () => {
    useDecisions([decisionItem({ evidence_count: 1 })], detailBody({ evidence: [detailBody().evidence[0]] }));
    const user = userEvent.setup();
    renderWithProviders(<DecisionsPage />);
    await user.click(await screen.findByText('Build auto-reports'));
    await screen.findByText(/we export every monday/i);
    expect(screen.queryByRole('button', { name: /remove quote/i })).not.toBeInTheDocument();
  });

  test('Add a quote searches highlights, hides already-cited ones, and cites via POST', async () => {
    const posted: string[] = [];
    useDecisions();
    server.use(
      http.get('/api/highlights', ({ request }) => {
        expect(new URL(request.url).searchParams.get('q')).toBeTruthy();
        const rows = [
          { id: 11, conversation_id: 1, utterance_id: 1, tag_key: 'pain', quote: 'We export every Monday', confidence: 0.9, status: 'accepted', origin: 'ai', conversation_title: 'A', conversation_happened_at: null, company_name: 'Acme', contact_names: ['Maria'] },
          { id: 40, conversation_id: 3, utterance_id: 2, tag_key: 'pain', quote: 'Exporting is our biggest chore', confidence: 0.9, status: 'accepted', origin: 'ai', conversation_title: 'C', conversation_happened_at: null, company_name: 'Globex', contact_names: ['Sam'] },
        ];
        return HttpResponse.json({ items: rows, total: 2, limit: 8, offset: 0 });
      }),
      http.post('/api/decisions/:id/evidence/:hid', ({ params }) => {
        posted.push(String(params.hid));
        return HttpResponse.json(detailBody(), { status: 201 });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<DecisionsPage />);
    await user.click(await screen.findByText('Build auto-reports'));
    await user.click(await screen.findByRole('button', { name: /^add a quote$/i }));
    const section = screen.getByRole('region', { name: /add a quote/i });
    await user.type(within(section).getByLabelText(/search quotes to cite/i), 'export');
    await within(section).findByText(/Exporting is our biggest chore/);
    expect(within(section).queryByText(/We export every Monday/)).not.toBeInTheDocument(); // already cited
    await user.click(within(section).getByRole('button', { name: /cite: exporting is our biggest chore/i }));
    await waitFor(() => expect(posted).toEqual(['40']));
  });

  test('draft decisions get a Draft tab and a Propose action (needs a quote)', async () => {
    let transition: Record<string, unknown> | null = null;
    useDecisions([decisionItem({ status: 'draft' })], detailBody({ status: 'draft' }));
    server.use(
      http.patch('/api/decisions/:id/status', async ({ request }) => {
        transition = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ id: 1, status: 'proposed' });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<DecisionsPage />);
    await user.click(await screen.findByRole('tab', { name: /draft/i }));
    await user.click(await screen.findByText('Build auto-reports'));
    await user.click(await screen.findByRole('button', { name: /^propose$/i }));
    await waitFor(() => expect(transition).toMatchObject({ status: 'proposed' }));
  });

  test('Propose is disabled for an empty draft', async () => {
    useDecisions([decisionItem({ status: 'draft', evidence_count: 0 })], detailBody({ status: 'draft', evidence: [] }));
    const user = userEvent.setup();
    renderWithProviders(<DecisionsPage />);
    await user.click(await screen.findByText('Build auto-reports'));
    expect(await screen.findByRole('button', { name: /^propose$/i })).toBeDisabled();
  });

  test('Save as draft creates a draft with owner and area, even with no quotes', async () => {
    let body: Record<string, unknown> | null = null;
    useDecisions();
    server.use(
      http.post('/api/decisions', async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ id: 9, title: 't', status: 'draft', integrity: 'ok' }, { status: 201 });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<DecisionsPage />);
    await user.click(await screen.findByText('New decision'));
    const dialog = screen.getByRole('dialog', { name: /create decision/i });
    await user.type(within(dialog).getByPlaceholderText(/decision title/i), 'Idea');
    await user.type(within(dialog).getByPlaceholderText(/rationale/i), 'Early thinking');
    await waitFor(() => expect(within(dialog).getByRole('option', { name: 'David' })).toBeInTheDocument());
    await user.selectOptions(within(dialog).getByLabelText(/^owner$/i), '1');
    await user.type(within(dialog).getByLabelText(/^area$/i), 'Pricing');
    await user.click(within(dialog).getByRole('button', { name: /save as draft/i }));
    await waitFor(() => expect(body).not.toBeNull());
    expect(body).toMatchObject({ status: 'draft', owner_id: 1, area: 'Pricing', evidence: [] });
  });
});

// ─── Hypotheses: archive/restore + paging ───

const hyp = (id: number, statement: string, over: Record<string, unknown> = {}) => ({
  id,
  statement,
  segment: null,
  status: 'open',
  created_by: 1,
  created_at: '2026-08-01T00:00:00Z',
  decided_at: null,
  rollup: {
    supports: { confirmed: 0, suggested: 0 },
    contradicts: { confirmed: 0, suggested: 0 },
    companies_supporting: 0,
    companies_contradicting: 0,
    last_evidence_at: null,
    grounding: 'hunch',
    pending_count: 0,
    grounding_reason: 'No evidence yet.',
  },
  verdict_hint: null,
  ...over,
});

describe('Hypotheses: archived section and paging', () => {
  test('Show archived lists archived hypotheses and Restore sets status back to open', async () => {
    let restored: Record<string, unknown> | null = null;
    let archivedList = [hyp(31, 'Archived belief about pricing tiers', { status: 'archived' })];
    server.use(
      http.get('/api/hypotheses', ({ request }) => {
        const status = new URL(request.url).searchParams.get('status');
        const items = status === 'archived' ? archivedList : [hyp(30, 'Active belief about onboarding flow')];
        return HttpResponse.json({ items, total: items.length });
      }),
      http.patch('/api/hypotheses/31', async ({ request }) => {
        restored = (await request.json()) as Record<string, unknown>;
        archivedList = [];
        return HttpResponse.json(hyp(31, 'Archived belief about pricing tiers'));
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<HypothesesPage />);
    await screen.findByText(/Active belief about onboarding/);
    expect(screen.queryByText(/Archived belief about pricing/)).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /show archived/i }));
    await screen.findByText(/Archived belief about pricing/);
    await user.click(screen.getByRole('button', { name: /restore: archived belief/i }));
    await waitFor(() => expect(restored).toEqual({ status: 'open' }));
    await waitFor(() => expect(screen.queryByTestId('archived-hypothesis')).not.toBeInTheDocument());
  });

  test('archived section says so when nothing is archived', async () => {
    server.use(
      http.get('/api/hypotheses', ({ request }) => {
        const archived = new URL(request.url).searchParams.get('status') === 'archived';
        const items = archived ? [] : [hyp(30, 'Only active belief here today')];
        return HttpResponse.json({ items, total: items.length });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<HypothesesPage />);
    await screen.findByText(/Only active belief/);
    await user.click(screen.getByRole('button', { name: /show archived/i }));
    expect(await screen.findByText(/nothing archived/i)).toBeInTheDocument();
  });

  test('the board loads every page, not just the first', async () => {
    const all = Array.from({ length: 5 }, (_, i) => hyp(100 + i, `Paged belief number ${i} for the board`));
    const offsets: number[] = [];
    server.use(
      http.get('/api/hypotheses', ({ request }) => {
        const offset = Number(new URL(request.url).searchParams.get('offset') ?? 0);
        offsets.push(offset);
        // The server caps a page at 2 here to force the client to keep going.
        return HttpResponse.json({ items: all.slice(offset, offset + 2), total: all.length });
      }),
    );
    renderWithProviders(<HypothesesPage />);
    await waitFor(() => expect(screen.getAllByTestId('hypothesis-card')).toHaveLength(5));
    expect(offsets).toEqual([0, 2, 4]);
  });
});
