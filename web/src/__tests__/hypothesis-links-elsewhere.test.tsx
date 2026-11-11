/**
 * Hypotheses PRD §5: hypotheses connect to the rest of the app.
 * - Explore quote cards get "Link to hypothesis"
 * - Decisions opens prefilled from a hypothesis + its confirmed quotes
 */
import { describe, test, expect } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { Routes, Route } from 'react-router-dom';
import { server } from '../test/mocks/server';
import { renderWithProviders } from '../test/render';
import { ExplorePage } from '../pages/ExplorePage';
import { DecisionsPage } from '../pages/DecisionsPage';

const hypothesisItem = {
  id: 5,
  statement: 'Mid-market teams renew only after a pilot',
  segment: 'Mid-market',
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
};

describe('Explore: Link to hypothesis', () => {
  test('links a quote to the chosen hypothesis with a stance, as confirmed evidence', async () => {
    const posted: unknown[] = [];
    server.use(
      http.get('/api/hypotheses', () => HttpResponse.json({ items: [hypothesisItem], total: 1 })),
      http.post('/api/hypotheses/5/links', async ({ request }) => {
        posted.push(await request.json());
        return HttpResponse.json({ id: 1, status: 'confirmed' }, { status: 201 });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(
      <Routes><Route path="/explore" element={<ExplorePage />} /></Routes>,
      { route: '/explore' },
    );
    const card = (await screen.findByText(/Every Monday I export all flagged listings/)).closest(
      '[data-testid="quote-card"]',
    ) as HTMLElement;
    await user.click(within(card).getByRole('button', { name: /link to hypothesis/i }));
    const group = await within(card).findByRole('group', { name: /link to hypothesis/i });
    await user.selectOptions(within(group).getByLabelText(/^hypothesis$/i), '5');
    await user.click(within(group).getByRole('button', { name: /^supports$/i }));
    await waitFor(() => expect(posted).toHaveLength(1));
    expect(posted[0]).toMatchObject({ stance: 'supports', confirm: true });
    expect(await within(card).findByRole('status')).toHaveTextContent(/linked as confirmed evidence/i);
  });

  test('says so when there are no hypotheses to link to', async () => {
    server.use(http.get('/api/hypotheses', () => HttpResponse.json({ items: [], total: 0 })));
    const user = userEvent.setup();
    renderWithProviders(
      <Routes><Route path="/explore" element={<ExplorePage />} /></Routes>,
      { route: '/explore' },
    );
    const card = (await screen.findByText(/Every Monday I export all flagged listings/)).closest(
      '[data-testid="quote-card"]',
    ) as HTMLElement;
    await user.click(within(card).getByRole('button', { name: /link to hypothesis/i }));
    expect(await within(card).findByText(/no hypotheses yet/i)).toBeInTheDocument();
  });
});

describe('Decisions: prefill from a hypothesis', () => {
  test('opens the create dialog with the hypothesis, preselected quotes, and sends hypothesis_id', async () => {
    let body: Record<string, unknown> | null = null;
    server.use(
      http.get('/api/hypotheses/5', () =>
        HttpResponse.json({ ...hypothesisItem, evidence: { supports: [], contradicts: [] }, questions: [] }),
      ),
      http.post('/api/decisions', async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ id: 1, title: 't', status: 'proposed', integrity: 'intact' }, { status: 201 });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<DecisionsPage />, {
      route: '/decisions?hypothesis_id=5&highlight_id=11&highlight_id=12',
    });
    const dialog = await screen.findByRole('dialog', { name: /create decision/i });
    expect(await within(dialog).findByTestId('linked-hypothesis')).toHaveTextContent(
      /Mid-market teams renew only after a pilot/,
    );
    expect(within(dialog).getByText(/2 selected/i)).toBeInTheDocument();
    await user.type(within(dialog).getByPlaceholderText(/decision title/i), 'Run pilots first');
    await user.type(within(dialog).getByPlaceholderText(/rationale/i), 'Because renewals follow pilots');
    await user.click(within(dialog).getByRole('button', { name: /^create$/i }));
    await waitFor(() => expect(body).not.toBeNull());
    expect(body).toMatchObject({ hypothesis_id: 5, evidence: [11, 12] });
  });
});
