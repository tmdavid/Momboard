/**
 * UX Audit Aug 17 2026 — behavioral tests for findings #1–#12.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { http, HttpResponse } from 'msw';
import { server } from '../test/mocks/server';

function createWrapper(initialEntries = ['/']) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={initialEntries}>{children}</MemoryRouter>
    </QueryClientProvider>
  );
}

// ─── #1: Decisions modal always opens ───
describe('UX #1: Decisions — New Decision always opens modal', () => {
  it('opens modal on + New Decision click even with no preselected highlight', async () => {
    const { DecisionsPage } = await import('../pages/DecisionsPage');
    render(<DecisionsPage />, { wrapper: createWrapper(['/decisions']) });

    await waitFor(() => expect(screen.getByText('+ New Decision')).toBeInTheDocument());
    await userEvent.click(screen.getByText('+ New Decision'));

    expect(screen.getByRole('dialog', { name: /create decision/i })).toBeInTheDocument();
    expect(screen.getByText(/decisions must cite evidence/i)).toBeInTheDocument();
  });

  it('opens modal automatically when highlight_id param is present', async () => {
    const { DecisionsPage } = await import('../pages/DecisionsPage');
    render(<DecisionsPage />, { wrapper: createWrapper(['/decisions?highlight_id=1']) });

    await waitFor(() => expect(screen.getByRole('dialog', { name: /create decision/i })).toBeInTheDocument());
  });
});

// ─── #2: Explore synthesis progress ───
describe('UX #2: Explore synthesis progress panel', () => {
  it('shows progress panel with counts and Cancel during synthesis', async () => {
    server.use(
      http.post('/api/syntheses', () =>
        HttpResponse.json({ id: 1, kind: 'synthesis', input_scope: {}, result: null, model: null, prompt_version: null, created_at: new Date().toISOString() }, { status: 201 })
      ),
      http.get('/api/syntheses/1', () =>
        HttpResponse.json({ id: 1, kind: 'synthesis', input_scope: {}, result: null, model: null, prompt_version: null, created_at: new Date().toISOString() })
      ),
    );

    const { ExplorePage } = await import('../pages/ExplorePage');
    render(<ExplorePage />, { wrapper: createWrapper(['/explore']) });

    await waitFor(() => expect(screen.getByText(/Synthesize this view/i)).toBeInTheDocument());
    await userEvent.click(screen.getByText(/Synthesize this view/i));

    await waitFor(() => expect(screen.getByText('Cancel')).toBeInTheDocument());
    expect(screen.getByRole('status', { name: /synthesis in progress/i })).toBeInTheDocument();
    expect(screen.getByText(/~30 s/)).toBeInTheDocument();
  });

  it('cancel stops synthesis progress', async () => {
    server.use(
      http.post('/api/syntheses', () =>
        HttpResponse.json({ id: 1, kind: 'synthesis', input_scope: {}, result: null, model: null, prompt_version: null, created_at: new Date().toISOString() }, { status: 201 })
      ),
      http.get('/api/syntheses/1', () =>
        HttpResponse.json({ id: 1, kind: 'synthesis', input_scope: {}, result: null, model: null, prompt_version: null, created_at: new Date().toISOString() })
      ),
    );

    const { ExplorePage } = await import('../pages/ExplorePage');
    render(<ExplorePage />, { wrapper: createWrapper(['/explore']) });

    await waitFor(() => expect(screen.getByText(/Synthesize this view/i)).toBeInTheDocument());
    await userEvent.click(screen.getByText(/Synthesize this view/i));

    await waitFor(() => expect(screen.getByText('Cancel')).toBeInTheDocument());
    await userEvent.click(screen.getByText('Cancel'));

    await waitFor(() => expect(screen.queryByText('Cancel')).not.toBeInTheDocument());
  });

  it('shows a retryable error when the synthesis job fails on the server', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    server.use(
      http.post('/api/syntheses', () =>
        HttpResponse.json({ id: 1, kind: 'synthesis', input_scope: {}, result: null, status: 'queued', error: null, model: null, prompt_version: null, created_at: new Date().toISOString() }, { status: 201 })
      ),
      http.get('/api/syntheses/1', () =>
        HttpResponse.json({ id: 1, kind: 'synthesis', input_scope: {}, result: null, status: 'error', error: 'Synthesis failed. Please retry.', model: null, prompt_version: null, created_at: new Date().toISOString() })
      ),
    );

    try {
      const { ExplorePage } = await import('../pages/ExplorePage');
      render(<ExplorePage />, { wrapper: createWrapper(['/explore']) });

      await waitFor(() => expect(screen.getByText(/Synthesize this view/i)).toBeInTheDocument());
      await user.click(screen.getByText(/Synthesize this view/i));
      await waitFor(() => expect(screen.getByText('Cancel')).toBeInTheDocument());
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2100);
      });

      await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Synthesis failed. Please retry.'));
      expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
      expect(screen.queryByText('Cancel')).not.toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });
});

// ─── #3: Notes bordered textarea with placeholder ───
describe('UX #3: Notes textarea', () => {
  it('renders textarea with placeholder and bordered style', async () => {
    const { NotesDrawer } = await import('../components/NotesDrawer');
    render(<NotesDrawer conversationId={1} />, { wrapper: createWrapper() });

    // Expand drawer
    await userEvent.click(screen.getByText(/Notes/));
    const textarea = screen.getByPlaceholderText('Write notes… markdown supported');
    expect(textarea).toBeInTheDocument();
    expect(textarea.className).toContain('border');
  });

  it('shows "Nothing to preview yet" when body is empty and Preview selected', async () => {
    server.use(
      http.get('/api/conversations/:id/note', () =>
        HttpResponse.json({ id: 1, conversation_id: 1, body_md: '', updated_by: 1, updated_at: '2026-08-12T14:00:00Z' })
      ),
    );

    const { NotesDrawer } = await import('../components/NotesDrawer');
    render(<NotesDrawer conversationId={1} />, { wrapper: createWrapper() });

    await userEvent.click(screen.getByText(/Notes/));
    await userEvent.click(screen.getByText('Preview'));
    await waitFor(() => expect(screen.getByText('Nothing to preview yet')).toBeInTheDocument());
  });
});

// ─── #4: Help popover ───
describe('UX #4: Help popover', () => {
  it('opens help popover with shortcuts and taxonomy on ? click', async () => {
    const { Layout } = await import('../components/Layout');
    render(
      <MemoryRouter>
        <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
          <Layout />
        </QueryClientProvider>
      </MemoryRouter>,
    );

    const helpBtn = screen.getByLabelText('Help');
    await userEvent.click(helpBtn);

    expect(screen.getByRole('dialog', { name: /help/i })).toBeInTheDocument();
    expect(screen.getByText(/Next \/ prev suggestion/)).toBeInTheDocument();
    expect(screen.getByText('Accept')).toBeInTheDocument();
    expect(screen.getByText('Reject')).toBeInTheDocument();
    expect(screen.getByText(/Taxonomy/)).toBeInTheDocument();
  });

  it('closes on Escape', async () => {
    const { Layout } = await import('../components/Layout');
    render(
      <MemoryRouter>
        <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
          <Layout />
        </QueryClientProvider>
      </MemoryRouter>,
    );

    await userEvent.click(screen.getByLabelText('Help'));
    expect(screen.getByRole('dialog', { name: /help/i })).toBeInTheDocument();

    fireEvent.keyDown(document, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('dialog', { name: /help/i })).not.toBeInTheDocument());
  });
});

// ─── #5: Digest markdown rendering ───
describe('UX #5: Digest renders markdown', () => {
  it('renders markdown not raw pre', async () => {
    server.use(
      http.get('/api/digest/preview', () =>
        HttpResponse.json({ markdown: '## 🤝 New Commitments\n\n- **Session with Tomas** (Acme)' })
      ),
    );

    const { DigestPage } = await import('../pages/DigestPage');
    render(<DigestPage />, { wrapper: createWrapper(['/digest']) });

    await userEvent.click(screen.getByTestId('digest-preview-btn'));
    await waitFor(() => expect(screen.getByTestId('digest-preview')).toBeInTheDocument());

    const preview = screen.getByTestId('digest-preview');
    // Should NOT contain <pre> raw content
    expect(preview.querySelector('pre')).toBeNull();
    // Should contain rendered bold
    expect(preview.innerHTML).toContain('<b>');
  });
});

// ─── #6: Hypotheses separate confirmed from suggested ───
describe('UX #6: Hypotheses evidence separation', () => {
  it('shows separate headings for confirmed and suggested links', async () => {
    server.use(
      http.get('/api/hypotheses', () =>
        HttpResponse.json([
          {
            id: 1,
            statement: 'Mid-market wont pay >10k without SLA',
            segment: null,
            status: 'open',
            created_by: 1,
            created_at: '2026-08-01T00:00:00Z',
            decided_at: null,
            rollup: { supports: { confirmed: 1, suggested: 2 }, contradicts: { confirmed: 0, suggested: 1 }, companies_supporting: 1, companies_contradicting: 0, last_evidence_at: null },
            verdict_hint: null,
          },
        ])
      ),
      http.get('/api/hypotheses/1', () =>
        HttpResponse.json({
          id: 1,
          statement: 'Mid-market wont pay >10k without SLA',
          segment: null,
          status: 'open',
          created_by: 1,
          created_at: '2026-08-01T00:00:00Z',
          decided_at: null,
          rollup: { supports: { confirmed: 1, suggested: 2 }, contradicts: { confirmed: 0, suggested: 1 }, companies_supporting: 1, companies_contradicting: 0, last_evidence_at: null },
          verdict_hint: null,
          evidence: {
            supports: [
              { link_id: 1, highlight_id: 1, quote: 'We set aside 40k', conversation_id: 1, conversation_title: 'Acme', utterance_id: null, company_name: 'Acme', contact_name: null, confidence: 0.9, origin: 'ai', status: 'confirmed', rationale: null },
              { link_id: 2, highlight_id: 2, quote: 'Budget is tight', conversation_id: 2, conversation_title: 'NW', utterance_id: null, company_name: 'NW', contact_name: null, confidence: 0.7, origin: 'ai', status: 'suggested', rationale: null },
            ],
            contradicts: [
              { link_id: 3, highlight_id: 3, quote: 'Happy to pay premium', conversation_id: 3, conversation_title: 'PF', utterance_id: null, company_name: 'PF', contact_name: null, confidence: 0.6, origin: 'ai', status: 'suggested', rationale: null },
            ],
          },
        })
      ),
    );

    const { HypothesesPage } = await import('../pages/HypothesesPage');
    render(<HypothesesPage />, { wrapper: createWrapper(['/hypotheses']) });

    await waitFor(() => expect(screen.getByText(/Mid-market/)).toBeInTheDocument());
    // Expand
    await userEvent.click(screen.getByText(/Mid-market/));

    await waitFor(() => {
      expect(screen.getByText(/Supports · confirmed/i)).toBeInTheDocument();
      expect(screen.getByText(/Supports · suggested \(AI\)/i)).toBeInTheDocument();
      expect(screen.getByText(/Contradicts · suggested \(AI\)/i)).toBeInTheDocument();
    });
  });
});

// ─── #7: Hypothesis meter deterministic ───
describe('UX #7: Hypothesis evidence meter', () => {
  it('shows grey track when 0 confirmed / 3 suggested (not full support)', async () => {
    server.use(
      http.get('/api/hypotheses', () =>
        HttpResponse.json([
          {
            id: 1,
            statement: 'All users want dashboards',
            segment: null,
            status: 'open',
            created_by: 1,
            created_at: '2026-08-01T00:00:00Z',
            decided_at: null,
            rollup: { supports: { confirmed: 0, suggested: 3 }, contradicts: { confirmed: 0, suggested: 0 }, companies_supporting: 0, companies_contradicting: 0, last_evidence_at: null },
            verdict_hint: null,
          },
        ])
      ),
    );

    const { HypothesesPage } = await import('../pages/HypothesesPage');
    render(<HypothesesPage />, { wrapper: createWrapper(['/hypotheses']) });

    await waitFor(() => expect(screen.getByRole('meter')).toBeInTheDocument());
    const meter = screen.getByRole('meter');
    // Should NOT have confirmed support segment
    expect(meter.querySelector('[data-testid="meter-confirmed-support"]')).toBeNull();
    // Should have suggested segment
    expect(meter.querySelector('[data-testid="meter-suggested"]')).toBeInTheDocument();
    // Accessible label should include counts
    expect(meter.getAttribute('aria-label')).toContain('0 confirmed support');
    expect(meter.getAttribute('aria-label')).toContain('3 suggested support');
  });
});

// ─── #10: Library processing stages ───
describe('UX #10: Library processing stages visible', () => {
  it('shows normalizing/tagging/analyzing stage labels', async () => {
    server.use(
      http.get('/api/conversations', () =>
        HttpResponse.json({
          items: [
            { id: 10, title: 'New call', happened_at: '2026-08-15T10:00:00Z', status: 'normalizing', interviewer: 'David', company: null, contacts: [], meta: null, created_at: '2026-08-15T10:00:00Z', tag_counts: {}, critique_score: null },
            { id: 11, title: 'Another call', happened_at: '2026-08-15T11:00:00Z', status: 'tagging', interviewer: 'David', company: null, contacts: [], meta: null, created_at: '2026-08-15T11:00:00Z', tag_counts: {}, critique_score: null },
          ],
          total: 2, limit: 50, offset: 0,
        })
      ),
    );

    const { LibraryPage } = await import('../pages/LibraryPage');
    render(<LibraryPage />, { wrapper: createWrapper(['/']) });

    await waitFor(() => {
      expect(screen.getByText('Normalizing…')).toBeInTheDocument();
      expect(screen.getByText('Tagging…')).toBeInTheDocument();
    });
  });
});

// ─── #11: HighlightPopover closes on Escape ───
describe('UX #11: HighlightPopover', () => {
  it('closes on Escape key', async () => {
    const { HighlightPopover } = await import('../components/HighlightPopover');
    const onClose = vi.fn();
    const highlight = { id: 1, conversation_id: 1, utterance_id: 2, tag_key: 'pain', quote: 'test', char_start: null, char_end: null, note: null, confidence: 0.9, origin: 'ai', status: 'suggested', created_at: '2026-08-12T12:00:00Z' };

    render(
      <HighlightPopover
        highlight={highlight}
        position={{ top: 100, left: 200 }}
        onAccept={() => {}}
        onReject={() => {}}
        onRetag={() => {}}
        onClose={onClose}
      />,
      { wrapper: createWrapper() },
    );

    expect(screen.getByRole('dialog', { name: /highlight review/i })).toBeInTheDocument();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalled();
  });
});

// ─── #12: Insights sparse charts ───
describe('UX #12: Insights sparse charts', () => {
  it('shows first-month message when only 1 data point', async () => {
    server.use(
      http.get('/api/stats', () =>
        HttpResponse.json({
          tag_counts_by_month: {
            '2026-08': { pain: 5, workaround: 2 },
          },
          critique_trend: [
            { date: '2026-08-12T00:00:00Z', score: 7, conversation_id: 1 },
          ],
          compliment_ratio_trend: [
            { date: '2026-08-12T00:00:00Z', ratio: 0.22, conversation_id: 1 },
          ],
          open_followups: [],
        })
      ),
    );

    const { InsightsPage } = await import('../pages/InsightsPage');
    render(<InsightsPage />, { wrapper: createWrapper(['/insights']) });

    await waitFor(() => {
      expect(screen.getByTestId('sparse-chart-msg')).toBeInTheDocument();
      expect(screen.getByTestId('sparse-chart-msg').textContent).toContain('First month');
    });
  });
});
