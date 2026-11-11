/**
 * T28 — Hypothesis Board UI (RED tests)
 *
 * These tests define the acceptance criteria for the Hypothesis Board page.
 * They will FAIL because no HypothesesPage, route, or API client exists yet.
 *
 * Acceptance criteria mapped:
 *  - Board/nav/route: Hypotheses link in nav, route renders the page
 *  - Cards with status chip and confirmed meter + hatched suggested extension
 *  - Expansion into evidence grouped supports/contradicts with quote links
 *  - Suggested link accept/reject optimistic interactions
 *  - Supported/refuted confirmation and decided_at/status refresh
 *  - New hypothesis composer: min 15 chars, validation, optimistic/query update
 *  - Loading/empty/error states
 *  - Keyboard accessibility
 */
import { describe, test, expect, vi } from 'vitest';
import { screen, waitFor, within, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { server } from '../test/mocks/server';
import { renderWithProviders } from '../test/render';
import { App } from '../App';
import type { HypothesisListItem } from '../api';

// ─── Mock data: REST contract for GET /api/hypotheses ───

const mockHypotheses = [
  {
    id: 1,
    statement: 'Enterprise brands will pay to eliminate the manual Monday export triage ritual',
    segment: 'enterprise',
    status: 'open',
    created_by: 1,
    created_at: '2026-07-20T09:00:00Z',
    decided_at: null,
    rollup: {
      supports: { confirmed: 4, suggested: 1 },
      contradicts: { confirmed: 1, suggested: 0 },
      companies_supporting: 3,
      companies_contradicting: 1,
      last_evidence_at: '2026-08-14T12:00:00Z',
    },
    verdict_hint: 'leaning-supported',
  },
  {
    id: 2,
    statement: 'Customers primarily want broader marketplace coverage (more platforms monitored)',
    segment: null,
    status: 'refuted',
    created_by: 1,
    created_at: '2026-07-05T09:00:00Z',
    decided_at: '2026-08-08T14:00:00Z',
    rollup: {
      supports: { confirmed: 1, suggested: 0 },
      contradicts: { confirmed: 6, suggested: 0 },
      companies_supporting: 1,
      companies_contradicting: 5,
      last_evidence_at: '2026-08-08T11:00:00Z',
    },
    verdict_hint: null,
  },
  {
    id: 3,
    statement: 'Detection speed matters more than coverage breadth for renewal decisions',
    segment: null,
    status: 'open',
    created_by: 1,
    created_at: '2026-08-09T09:00:00Z',
    decided_at: null,
    rollup: {
      supports: { confirmed: 2, suggested: 1 },
      contradicts: { confirmed: 0, suggested: 0 },
      companies_supporting: 2,
      companies_contradicting: 0,
      last_evidence_at: '2026-08-13T10:00:00Z',
    },
    verdict_hint: null,
  },
];

// ─── Mock data: GET /api/hypotheses/:id (detail with evidence) ───

const mockHypothesisDetail = {
  id: 1,
  statement: 'Enterprise brands will pay to eliminate the manual Monday export triage ritual',
  segment: 'enterprise',
  status: 'open',
  created_by: 1,
  created_at: '2026-07-20T09:00:00Z',
  decided_at: null,
  rollup: {
    supports: { confirmed: 4, suggested: 1 },
    contradicts: { confirmed: 1, suggested: 0 },
    companies_supporting: 3,
    companies_contradicting: 1,
    last_evidence_at: '2026-08-14T12:00:00Z',
  },
  verdict_hint: 'leaning-supported',
  evidence: {
    supports: [
      {
        link_id: 101,
        highlight_id: 1,
        quote: 'Every Monday I export all flagged listings to Excel and clean them up by hand',
        conversation_id: 1,
        conversation_title: 'Discovery — counterfeit listings workflow',
        utterance_id: 2,
        company_name: 'Acme Watches',
        contact_name: 'Jane Doe',
        confidence: 0.92,
        origin: 'ai',
        status: 'confirmed',
        rationale: 'Direct evidence of painful manual Monday ritual',
      },
      {
        link_id: 102,
        highlight_id: 5,
        quote: 'If it saves Maria\'s Mondays it pays for itself, but procurement needs an ROI sheet',
        conversation_id: 3,
        conversation_title: 'Northwind — procurement process',
        utterance_id: 8,
        company_name: 'Northwind Apparel',
        contact_name: 'Karl Gruber',
        confidence: 0.89,
        origin: 'ai',
        status: 'confirmed',
        rationale: 'Explicit willingness to pay to eliminate Monday export',
      },
      {
        link_id: 103,
        highlight_id: 7,
        quote: 'We set aside a brand-protection line item this year — around €40k',
        conversation_id: 1,
        conversation_title: 'Discovery — counterfeit listings workflow',
        utterance_id: 5,
        company_name: 'Acme Watches',
        contact_name: 'Jane Doe',
        confidence: 0.95,
        origin: 'human',
        status: 'confirmed',
        rationale: 'Budget allocated = willingness to pay',
      },
      {
        link_id: 104,
        highlight_id: 9,
        quote: 'Our ops lead spends every Monday morning on this, easily three hours',
        conversation_id: 4,
        conversation_title: 'Bergmann brand-protection setup',
        utterance_id: 3,
        company_name: 'Bergmann GmbH',
        contact_name: 'Luisa Trent',
        confidence: 0.88,
        origin: 'ai',
        status: 'confirmed',
        rationale: 'Another company confirming weekly manual triage pain',
      },
      {
        link_id: 105,
        highlight_id: 11,
        quote: 'My intern screenshots suspicious listings into a shared drive folder every Friday',
        conversation_id: 5,
        conversation_title: 'Lumina brand — gray market',
        utterance_id: 6,
        company_name: 'Lumina',
        contact_name: 'Anya Vogt',
        confidence: 0.72,
        origin: 'ai',
        status: 'suggested',
        rationale: 'Similar manual ritual suggesting broader pattern',
      },
    ],
    contradicts: [
      {
        link_id: 106,
        highlight_id: 12,
        quote: 'Honestly the export is fine, it\'s the nine takedown templates that kill us',
        conversation_id: 5,
        conversation_title: 'Lumina brand — gray market',
        utterance_id: 9,
        company_name: 'Lumina',
        contact_name: 'Anya Vogt',
        confidence: 0.85,
        origin: 'ai',
        status: 'confirmed',
        rationale: 'Export itself not seen as the pain point',
      },
    ],
  },
};

// ─── MSW handlers for hypothesis endpoints ───

const hypothesesHandlers = [
  http.get('/api/hypotheses', () => {
    return HttpResponse.json({ items: mockHypotheses, total: mockHypotheses.length });
  }),

  // Specific paths must come before '/api/hypotheses/:id' (same order as the server routes).
  http.get('/api/hypotheses/segments', () => HttpResponse.json({ items: [] })),
  http.get('/api/hypotheses/band-rules', () =>
    HttpResponse.json({
      items: [
        { band: 'grounded', label: 'Grounded', rule: '3+ confirmed supporting quotes from 2+ companies, and at most 1 contradicting' },
        { band: 'hunch', label: 'Hunch', rule: 'No confirmed quotes yet' },
      ],
      grounded_min_support: 3, grounded_min_companies: 2, grounded_max_contradict: 1,
      contested_min_each: 2, refuted_min_contradict: 3, refuted_ratio: 2,
    }),
  ),
  http.get('/api/hypotheses/:id/history', () => HttpResponse.json({ items: [] })),

  http.get('/api/hypotheses/:id', ({ params }) => {
    if (params.id === '1') {
      return HttpResponse.json(mockHypothesisDetail);
    }
    return new HttpResponse(null, { status: 404 });
  }),

  http.post('/api/hypotheses', async ({ request }) => {
    const body = (await request.json()) as { statement: string; segment?: string };
    return HttpResponse.json(
      {
        id: 99,
        statement: body.statement,
        segment: body.segment || null,
        status: 'open',
        created_by: 1,
        created_at: new Date().toISOString(),
        decided_at: null,
        rollup: {
          supports: { confirmed: 0, suggested: 0 },
          contradicts: { confirmed: 0, suggested: 0 },
          companies_supporting: 0,
          companies_contradicting: 0,
          last_evidence_at: null,
        },
        verdict_hint: null,
      },
      { status: 201 },
    );
  }),

  http.patch('/api/hypotheses/:id', async ({ request, params }) => {
    const body = (await request.json()) as { status?: string };
    const hyp = mockHypotheses.find((h) => h.id === Number(params.id));
    return HttpResponse.json({
      ...hyp,
      status: body.status || hyp?.status,
      decided_at: body.status && body.status !== 'open' ? new Date().toISOString() : null,
    });
  }),

  http.patch('/api/hypothesis-links/:id', async ({ request, params }) => {
    const body = (await request.json()) as { status: 'confirmed' | 'rejected' };
    // Find the link in the detail mock
    const allLinks = [
      ...mockHypothesisDetail.evidence.supports,
      ...mockHypothesisDetail.evidence.contradicts,
    ];
    const link = allLinks.find((l) => l.link_id === Number(params.id));
    return HttpResponse.json({ ...link, status: body.status });
  }),

  // T48: evidence-gated intake
  http.post('/api/hypotheses/intake', async ({ request }) => {
    const body = (await request.json()) as { statement: string };
    return HttpResponse.json({
      statement: body.statement,
      segment: null,
      matches: [
        {
          highlight_id: 501,
          quote: 'Every Monday I export it to Excel and clean it by hand',
          tag_key: 'workaround',
          conversation_id: 1,
          relation: 'supports',
          confidence: 0.9,
          rationale: 'Describes the recurring manual workaround.',
          strong: true,
        },
      ],
      grounding_preview: 'grounded',
      suggested_questions: [],
    });
  }),

  http.post('/api/hypotheses/intake/commit', async ({ request }) => {
    const body = (await request.json()) as { statement: string };
    return HttpResponse.json(
      { id: 999, statement: body.statement, segment: null, status: 'open', created_at: new Date().toISOString() },
      { status: 201 },
    );
  }),
];

// ─── Helper: render the full app at /hypotheses route ───

function renderHypothesesPage() {
  server.use(...hypothesesHandlers);
  return renderWithProviders(<App />, { route: '/hypotheses' });
}

// ═══════════════════════════════════════════════════════════════════════════════
// Board / Nav / Route
// ═══════════════════════════════════════════════════════════════════════════════

describe('T28: Hypotheses board — navigation and route', () => {
  test('nav contains a "Hypotheses" link that navigates to /hypotheses', async () => {
    server.use(...hypothesesHandlers);
    renderWithProviders(<App />, { route: '/' });

    const nav = await screen.findByRole('navigation');
    const link = within(nav).getByRole('link', { name: /hypotheses/i });
    expect(link).toBeInTheDocument();
    expect(link).toHaveAttribute('href', '/hypotheses');
  });

  test('navigating to /hypotheses renders the hypothesis board page', async () => {
    renderHypothesesPage();

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /hypotheses/i })).toBeInTheDocument();
    });
  });

  test('Hypotheses nav link is active when on /hypotheses route', async () => {
    renderHypothesesPage();

    await waitFor(() => {
      const nav = screen.getByRole('navigation');
      const link = within(nav).getByRole('link', { name: /hypotheses/i });
      // Active links get the accent styling class
      expect(link).toHaveClass('font-semibold');
    });
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// Cards with status chip and evidence meter
// ═══════════════════════════════════════════════════════════════════════════════

describe('T28: Hypotheses board — card list with status and meter', () => {
  test('board lists hypotheses with their statement text', async () => {
    renderHypothesesPage();

    await waitFor(() => {
      expect(
        screen.getByText(/Enterprise brands will pay to eliminate/),
      ).toBeInTheDocument();
      expect(
        screen.getByText(/Customers primarily want broader marketplace coverage/),
      ).toBeInTheDocument();
      expect(
        screen.getByText(/Detection speed matters more than coverage/),
      ).toBeInTheDocument();
    });
  });

  test('cards show a status chip only when the status is not the default "open"', async () => {
    renderHypothesesPage();

    await waitFor(() => {
      // Band columns carry the primary state; the legacy status chip appears only
      // for non-default statuses (here: the refuted hypothesis).
      expect(screen.getByText('REFUTED')).toBeInTheDocument();
      expect(screen.queryByText('OPEN')).not.toBeInTheDocument();
    });
  });

  test('meter shows confirmed evidence as solid fill proportional to supports/(supports+contradicts)', async () => {
    renderHypothesesPage();

    await waitFor(() => {
      // Hypothesis 1: confirmed supports=4, confirmed contradicts=1 → fill width ≈ 80%
      // The meter should have a fill element with a width style
      const firstCard = screen.getByText(/Enterprise brands will pay/).closest('[data-testid="hypothesis-card"]') ||
        screen.getByText(/Enterprise brands will pay/).closest('article');
      expect(firstCard).toBeInTheDocument();
      const meter = within(firstCard! as HTMLElement).getByRole('meter') || within(firstCard! as HTMLElement).getByTestId('evidence-meter');
      expect(meter).toBeInTheDocument();
    });
  });

  test('meter shows suggested evidence as hatched/striped extension beyond confirmed fill', async () => {
    renderHypothesesPage();

    await waitFor(() => {
      // Hypothesis 1 has suggested=1 → hatched extension segment visible
      const firstCard = screen.getByText(/Enterprise brands will pay/).closest('[data-testid="hypothesis-card"]') ||
        screen.getByText(/Enterprise brands will pay/).closest('article');
      expect(firstCard).toBeInTheDocument();
      const hatchedSegment = within(firstCard! as HTMLElement).getByTestId('meter-suggested') ||
        within(firstCard! as HTMLElement).getByLabelText(/suggested/i);
      expect(hatchedSegment).toBeInTheDocument();
    });
  });

  test('card shows evidence stats summary (e.g. "4 support (3 companies) · 1 contradicts · 1 suggested")', async () => {
    renderHypothesesPage();

    await waitFor(() => {
      expect(screen.getByText(/4 support/i)).toBeInTheDocument();
      expect(screen.getByText(/3 companies/i)).toBeInTheDocument();
      expect(screen.getByText(/1 contradicts/i)).toBeInTheDocument();
    });
  });

  test('card with verdict_hint shows the hint text (e.g. "leaning supported")', async () => {
    renderHypothesesPage();

    await waitFor(() => {
      expect(screen.getByText(/leaning supported/i)).toBeInTheDocument();
    });
  });

  test('refuted hypothesis shows decided_at date in verdict area', async () => {
    renderHypothesesPage();

    await waitFor(() => {
      // Hypothesis 2: refuted on Aug 8 → "refuted Aug 8" or similar
      expect(screen.getByText(/refuted.*aug/i)).toBeInTheDocument();
    });
  });

  test('card with pending suggested links shows a "to review" badge with count', async () => {
    renderHypothesesPage();

    await waitFor(() => {
      // Hypothesis 1 has 1 suggested link → "1 to review"
      // Hypothesis 3 also has 1 suggested link → "1 to review"
      const badges = screen.getAllByText(/1 to review/i);
      expect(badges.length).toBeGreaterThanOrEqual(1);
    });
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// Card expansion into evidence detail
// ═══════════════════════════════════════════════════════════════════════════════

describe('T28: Hypotheses board — evidence expansion', () => {
  test('clicking a card expands it to show evidence detail', async () => {
    const user = userEvent.setup();
    renderHypothesesPage();

    await waitFor(() => {
      expect(screen.getByText(/Enterprise brands will pay/)).toBeInTheDocument();
    });

    const heading = screen.getByText(/Enterprise brands will pay/);
    await user.click(heading);

    await waitFor(() => {
      // Evidence grouped by stance should appear
      expect(screen.getByText(/supports.*confirmed/i)).toBeInTheDocument();
    });
  });

  test('expanded evidence is grouped by stance: supports section and contradicts section', async () => {
    const user = userEvent.setup();
    renderHypothesesPage();

    await waitFor(() => {
      expect(screen.getByText(/Enterprise brands will pay/)).toBeInTheDocument();
    });
    await user.click(screen.getByText(/Enterprise brands will pay/));

    await waitFor(() => {
      // Both stance group headings appear
      const region = screen.getByRole('region', { name: /evidence/i });
      expect(within(region).getAllByText(/supports/i).length).toBeGreaterThan(0);
      expect(within(region).getAllByText(/contradicts/i).length).toBeGreaterThan(0);
    });
  });

  test('each evidence quote shows the quote text in blockquote style', async () => {
    const user = userEvent.setup();
    renderHypothesesPage();

    await waitFor(() => {
      expect(screen.getByText(/Enterprise brands will pay/)).toBeInTheDocument();
    });
    await user.click(screen.getByText(/Enterprise brands will pay/));

    await waitFor(() => {
      expect(
        screen.getByText(/Every Monday I export all flagged listings/),
      ).toBeInTheDocument();
      expect(
        screen.getByText(/Honestly the export is fine/),
      ).toBeInTheDocument();
    });
  });

  test('evidence quotes have links to their source conversation anchored at utterance', async () => {
    const user = userEvent.setup();
    renderHypothesesPage();

    await waitFor(() => {
      expect(screen.getByText(/Enterprise brands will pay/)).toBeInTheDocument();
    });
    await user.click(screen.getByText(/Enterprise brands will pay/));

    await waitFor(() => {
      // Each quote has a link like "Acme Watches ↗" that navigates to /conversations/1#utterance-2
      const links = screen.getAllByRole('link', { name: /acme watches/i });
      expect(links.length).toBeGreaterThan(0);
      expect(links[0]).toHaveAttribute('href', expect.stringContaining('/conversations/1'));
      expect(links[0]).toHaveAttribute('href', expect.stringContaining('#utterance-'));
    });
  });

  test('evidence from different companies shows their company name as source link', async () => {
    const user = userEvent.setup();
    renderHypothesesPage();

    await waitFor(() => {
      expect(screen.getByText(/Enterprise brands will pay/)).toBeInTheDocument();
    });
    await user.click(screen.getByText(/Enterprise brands will pay/));

    await waitFor(() => {
      expect(screen.getByText(/Northwind/i)).toBeInTheDocument();
      expect(screen.getByText(/Bergmann/i)).toBeInTheDocument();
      // Lumina appears in both supports and contradicts sections
      expect(screen.getAllByText(/Lumina/i).length).toBeGreaterThanOrEqual(1);
    });
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// Suggested link accept/reject (optimistic)
// ═══════════════════════════════════════════════════════════════════════════════

describe('T28: Hypotheses board — suggested link accept/reject', () => {
  test('suggested links render with a distinct visual treatment (dashed border or highlight)', async () => {
    const user = userEvent.setup();
    renderHypothesesPage();

    await waitFor(() => {
      expect(screen.getByText(/Enterprise brands will pay/)).toBeInTheDocument();
    });
    await user.click(screen.getByText(/Enterprise brands will pay/));

    await waitFor(() => {
      // The suggested evidence (link_id 105) should have a "suggested" indicator
      const suggestedQuote = screen.getByText(/My intern screenshots suspicious listings/);
      const container = suggestedQuote.closest('[data-status="suggested"]') ||
        suggestedQuote.closest('.suggested');
      expect(container).toBeInTheDocument();
    });
  });

  test('suggested links have accept and reject buttons', async () => {
    const user = userEvent.setup();
    renderHypothesesPage();

    await waitFor(() => {
      expect(screen.getByText(/Enterprise brands will pay/)).toBeInTheDocument();
    });
    await user.click(screen.getByText(/Enterprise brands will pay/));

    await waitFor(() => {
      const suggestedQuote = screen.getByText(/My intern screenshots suspicious listings/);
      const container = suggestedQuote.closest('[data-status="suggested"]') ||
        suggestedQuote.closest('div');
      expect(container).toBeInTheDocument();
      const acceptBtn = within(container! as HTMLElement).getByRole('button', { name: /accept|confirm|supports/i });
      const rejectBtn = within(container! as HTMLElement).getByRole('button', { name: /reject|dismiss/i });
      expect(acceptBtn).toBeInTheDocument();
      expect(rejectBtn).toBeInTheDocument();
    });
  });

  test('clicking accept on a suggested link optimistically moves it to confirmed', async () => {
    const user = userEvent.setup();
    renderHypothesesPage();

    await waitFor(() => {
      expect(screen.getByText(/Enterprise brands will pay/)).toBeInTheDocument();
    });
    await user.click(screen.getByText(/Enterprise brands will pay/));

    let acceptBtn: HTMLElement;
    await waitFor(() => {
      const suggestedQuote = screen.getByText(/My intern screenshots suspicious listings/);
      const container = suggestedQuote.closest('[data-status="suggested"]') ||
        suggestedQuote.closest('div');
      acceptBtn = within(container! as HTMLElement).getByRole('button', { name: /accept|confirm|supports/i });
    });

    await user.click(acceptBtn!);

    // Optimistically: the link should no longer appear as "suggested"
    await waitFor(() => {
      const suggestedQuote = screen.getByText(/My intern screenshots suspicious listings/);
      const container = suggestedQuote.closest('[data-status="suggested"]') ||
        suggestedQuote.closest('.suggested');
      expect(container).not.toBeInTheDocument();
    });
  });

  test('clicking reject on a suggested link optimistically removes it from the list', async () => {
    const user = userEvent.setup();
    renderHypothesesPage();

    await waitFor(() => {
      expect(screen.getByText(/Enterprise brands will pay/)).toBeInTheDocument();
    });
    await user.click(screen.getByText(/Enterprise brands will pay/));

    let rejectBtn: HTMLElement;
    await waitFor(() => {
      const suggestedQuote = screen.getByText(/My intern screenshots suspicious listings/);
      const container = suggestedQuote.closest('[data-status="suggested"]') ||
        suggestedQuote.closest('div');
      rejectBtn = within(container! as HTMLElement).getByRole('button', { name: /reject|dismiss/i });
    });

    await user.click(rejectBtn!);

    // Optimistically: the rejected quote disappears
    await waitFor(() => {
      expect(
        screen.queryByText(/My intern screenshots suspicious listings/),
      ).not.toBeInTheDocument();
    });
  });

  test('accept sends PATCH /api/hypothesis-links/:id with status "confirmed"', async () => {
    const patchSpy = vi.fn();
    server.use(
      http.patch('/api/hypothesis-links/:id', async ({ request, params }) => {
        const body = (await request.json()) as { status: string };
        patchSpy({ id: params.id, status: body.status });
        return HttpResponse.json({ link_id: Number(params.id), status: body.status });
      }),
      ...hypothesesHandlers,
    );

    const user = userEvent.setup();
    renderWithProviders(<App />, { route: '/hypotheses' });

    await waitFor(() => {
      expect(screen.getByText(/Enterprise brands will pay/)).toBeInTheDocument();
    });
    await user.click(screen.getByText(/Enterprise brands will pay/));

    await waitFor(() => {
      expect(screen.getByText(/My intern screenshots suspicious listings/)).toBeInTheDocument();
    });

    const suggestedQuote = screen.getByText(/My intern screenshots suspicious listings/);
    const container = suggestedQuote.closest('[data-status="suggested"]') || suggestedQuote.closest('div');
    const acceptBtn = within(container! as HTMLElement).getByRole('button', { name: /accept|confirm|supports/i });
    await user.click(acceptBtn);

    await waitFor(() => {
      expect(patchSpy).toHaveBeenCalledWith({ id: '105', status: 'confirmed' });
    });
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// Supported / Refuted confirmation and decided_at refresh
// ═══════════════════════════════════════════════════════════════════════════════

describe('T28: Hypotheses board — mark supported/refuted confirmation', () => {
  test('expanded card shows "Mark supported", "Mark refuted", and "Park" action buttons', async () => {
    const user = userEvent.setup();
    renderHypothesesPage();

    await waitFor(() => {
      expect(screen.getByText(/Enterprise brands will pay/)).toBeInTheDocument();
    });
    await user.click(screen.getByText(/Enterprise brands will pay/));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /mark supported/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /mark refuted/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /park/i })).toBeInTheDocument();
    });
  });

  test('clicking "Mark supported" shows a confirmation dialog before proceeding', async () => {
    const user = userEvent.setup();
    renderHypothesesPage();

    await waitFor(() => {
      expect(screen.getByText(/Enterprise brands will pay/)).toBeInTheDocument();
    });
    await user.click(screen.getByText(/Enterprise brands will pay/));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /mark supported/i })).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /mark supported/i }));

    // A confirmation dialog or inline confirm should appear
    await waitFor(() => {
      expect(
        screen.getByText(/are you sure|confirm/i),
      ).toBeInTheDocument();
    });
  });

  test('confirming "Mark supported" sends PATCH with status "supported" and updates the card', async () => {
    const patchSpy = vi.fn();
    server.use(
      http.patch('/api/hypotheses/:id', async ({ request, params }) => {
        const body = (await request.json()) as { status: string };
        patchSpy({ id: params.id, status: body.status });
        return HttpResponse.json({
          ...mockHypotheses[0],
          status: body.status,
          decided_at: new Date().toISOString(),
        });
      }),
      ...hypothesesHandlers,
    );

    const user = userEvent.setup();
    renderWithProviders(<App />, { route: '/hypotheses' });

    await waitFor(() => {
      expect(screen.getByText(/Enterprise brands will pay/)).toBeInTheDocument();
    });
    await user.click(screen.getByText(/Enterprise brands will pay/));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /mark supported/i })).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /mark supported/i }));

    // Confirm the action
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /confirm|yes/i })).toBeInTheDocument();
    });
    await user.click(screen.getByRole('button', { name: /confirm|yes/i }));

    await waitFor(() => {
      expect(patchSpy).toHaveBeenCalledWith({ id: '1', status: 'supported' });
    });
  });

  test('after marking supported, the status chip updates to "SUPPORTED" and decided_at is shown', async () => {
    server.use(
      ...hypothesesHandlers,
      http.patch('/api/hypotheses/:id', async ({ request }) => {
        const body = (await request.json()) as { status: string };
        return HttpResponse.json({
          ...mockHypotheses[0],
          status: body.status,
          decided_at: '2026-08-16T14:00:00Z',
        });
      }),
    );

    const user = userEvent.setup();
    renderWithProviders(<App />, { route: '/hypotheses' });

    await waitFor(() => {
      expect(screen.getByText(/Enterprise brands will pay/)).toBeInTheDocument();
    });
    await user.click(screen.getByText(/Enterprise brands will pay/));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /mark supported/i })).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /mark supported/i }));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /confirm|yes/i })).toBeInTheDocument();
    });
    await user.click(screen.getByRole('button', { name: /confirm|yes/i }));

    await waitFor(() => {
      expect(screen.getByText('SUPPORTED')).toBeInTheDocument();
    });
  });

  test('clicking "Mark refuted" shows confirmation and sends status "refuted"', async () => {
    const patchSpy = vi.fn();
    server.use(
      http.patch('/api/hypotheses/:id', async ({ request, params }) => {
        const body = (await request.json()) as { status: string };
        patchSpy({ id: params.id, status: body.status });
        return HttpResponse.json({
          ...mockHypotheses[0],
          status: body.status,
          decided_at: new Date().toISOString(),
        });
      }),
      ...hypothesesHandlers,
    );

    const user = userEvent.setup();
    renderWithProviders(<App />, { route: '/hypotheses' });

    await waitFor(() => {
      expect(screen.getByText(/Enterprise brands will pay/)).toBeInTheDocument();
    });
    await user.click(screen.getByText(/Enterprise brands will pay/));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /mark refuted/i })).toBeInTheDocument();
    });
    await user.click(screen.getByRole('button', { name: /mark refuted/i }));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /confirm|yes/i })).toBeInTheDocument();
    });
    await user.click(screen.getByRole('button', { name: /confirm|yes/i }));

    await waitFor(() => {
      expect(patchSpy).toHaveBeenCalledWith({ id: '1', status: 'refuted' });
    });
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// New hypothesis composer
// ═══════════════════════════════════════════════════════════════════════════════

describe('T28: Hypotheses board — new hypothesis composer', () => {
  test('composer has an input field with placeholder and an "Add hypothesis" button', async () => {
    renderHypothesesPage();

    await waitFor(() => {
      const input = screen.getByPlaceholderText(/falsifiable/i);
      expect(input).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /add hypothesis/i })).toBeInTheDocument();
    });
  });

  test('add button is disabled when input is empty', async () => {
    renderHypothesesPage();

    await waitFor(() => {
      const btn = screen.getByRole('button', { name: /add hypothesis/i });
      expect(btn).toHaveAttribute('aria-disabled', 'true');
    });
  });

  test('shows validation error when statement is fewer than 15 characters', async () => {
    const user = userEvent.setup();
    renderHypothesesPage();

    await waitFor(() => {
      expect(screen.getByPlaceholderText(/falsifiable/i)).toBeInTheDocument();
    });

    const input = screen.getByPlaceholderText(/falsifiable/i);
    await user.type(input, 'Too short');

    const btn = screen.getByRole('button', { name: /add hypothesis/i });
    await user.click(btn);

    await waitFor(() => {
      expect(screen.getByText(/at least 15 characters/i)).toBeInTheDocument();
    });
  });

  test('add button becomes enabled once input has 15+ characters', async () => {
    const user = userEvent.setup();
    renderHypothesesPage();

    await waitFor(() => {
      expect(screen.getByPlaceholderText(/falsifiable/i)).toBeInTheDocument();
    });

    const input = screen.getByPlaceholderText(/falsifiable/i);
    await user.type(input, 'Mid-market brands wont pay without SLA');

    await waitFor(() => {
      const btn = screen.getByRole('button', { name: /add hypothesis/i });
      expect(btn).toBeEnabled();
    });
  });

  test('submitting a valid hypothesis adds it optimistically to the list', async () => {
    const user = userEvent.setup();
    renderHypothesesPage();

    await waitFor(() => {
      expect(screen.getByPlaceholderText(/falsifiable/i)).toBeInTheDocument();
    });

    const input = screen.getByPlaceholderText(/falsifiable/i);
    const statement = 'Mid-market brands will not pay more than €10k without a detection-speed SLA';
    await user.type(input, statement);

    const btn = screen.getByRole('button', { name: /add hypothesis/i });
    await user.click(btn);

    // Optimistically appears in the list
    await waitFor(() => {
      expect(screen.getByText(statement)).toBeInTheDocument();
    });
  });

  test('keeps a valid card when POST returns the basic hypothesis response', async () => {
    const statement = 'Operations teams need audit-ready evidence before they will automate enforcement';
    const basicResponseSpy = vi.fn();
    let createdListItem: HypothesisListItem | null = null;
    const user = userEvent.setup();
    renderHypothesesPage();
    server.use(
      http.post('/api/hypotheses', async ({ request }) => {
        const body = (await request.json()) as { statement: string };
        basicResponseSpy();
        const createdAt = new Date().toISOString();
        createdListItem = {
          id: 99,
          statement: body.statement,
          segment: null,
          status: 'open',
          created_by: 1,
          created_at: createdAt,
          decided_at: null,
          rollup: {
            supports: { confirmed: 0, suggested: 0 },
            contradicts: { confirmed: 0, suggested: 0 },
            companies_supporting: 0,
            companies_contradicting: 0,
            last_evidence_at: null,
          },
          verdict_hint: null,
        };
        return HttpResponse.json(
          {
            id: 99,
            statement: body.statement,
            segment: null,
            status: 'open',
            created_by: 1,
            created_at: createdAt,
            decided_at: null,
          },
          { status: 201 },
        );
      }),
      http.get('/api/hypotheses', () =>
        HttpResponse.json(
          (() => {
            const items = createdListItem ? [createdListItem, ...mockHypotheses] : mockHypotheses;
            return { items, total: items.length };
          })(),
        ),
      ),
    );

    const input = await screen.findByPlaceholderText(/falsifiable/i);
    await user.type(input, statement);
    await user.click(screen.getByRole('button', { name: /add hypothesis/i }));

    await waitFor(() => {
      expect(basicResponseSpy).toHaveBeenCalledOnce();
      const card = screen.getByText(statement).closest('[data-testid="hypothesis-card"]');
      expect(card).toBeInTheDocument();
      expect(within(card as HTMLElement).getByRole('meter')).toBeInTheDocument();
    });
  });

  test('after successful submission, the input is cleared', async () => {
    const user = userEvent.setup();
    renderHypothesesPage();

    await waitFor(() => {
      expect(screen.getByPlaceholderText(/falsifiable/i)).toBeInTheDocument();
    });

    const input = screen.getByPlaceholderText(/falsifiable/i);
    await user.type(input, 'Mid-market brands will not pay more than €10k without SLA');

    const btn = screen.getByRole('button', { name: /add hypothesis/i });
    await user.click(btn);

    await waitFor(() => {
      expect(input).toHaveValue('');
    });
  });

  test('submission sends POST /api/hypotheses with the statement', async () => {
    const postSpy = vi.fn();
    server.use(
      http.post('/api/hypotheses', async ({ request }) => {
        const body = (await request.json()) as { statement: string };
        postSpy(body);
        return HttpResponse.json(
          { id: 99, statement: body.statement, status: 'open', created_at: new Date().toISOString(), decided_at: null, rollup: { supports: { confirmed: 0, suggested: 0 }, contradicts: { confirmed: 0, suggested: 0 }, companies_supporting: 0, companies_contradicting: 0, last_evidence_at: null }, verdict_hint: null },
          { status: 201 },
        );
      }),
      ...hypothesesHandlers,
    );

    const user = userEvent.setup();
    renderWithProviders(<App />, { route: '/hypotheses' });

    await waitFor(() => {
      expect(screen.getByPlaceholderText(/falsifiable/i)).toBeInTheDocument();
    });

    const input = screen.getByPlaceholderText(/falsifiable/i);
    await user.type(input, 'Brands care more about speed than coverage');
    await user.click(screen.getByRole('button', { name: /add hypothesis/i }));

    await waitFor(() => {
      expect(postSpy).toHaveBeenCalledWith(
        expect.objectContaining({ statement: 'Brands care more about speed than coverage' }),
      );
    });
  });

  test('if POST fails, the optimistic entry is rolled back and error shown', async () => {
    server.use(
      http.post('/api/hypotheses', () => {
        return new HttpResponse(null, { status: 500 });
      }),
      ...hypothesesHandlers,
    );

    const user = userEvent.setup();
    renderWithProviders(<App />, { route: '/hypotheses' });

    await waitFor(() => {
      expect(screen.getByPlaceholderText(/falsifiable/i)).toBeInTheDocument();
    });

    const statement = 'This hypothesis will fail to save due to server error';
    const input = screen.getByPlaceholderText(/falsifiable/i);
    await user.type(input, statement);
    await user.click(screen.getByRole('button', { name: /add hypothesis/i }));

    // Eventually the optimistic entry should be rolled back
    await waitFor(() => {
      expect(screen.queryByText(statement)).not.toBeInTheDocument();
    });

    // And an error message shown
    expect(screen.getByRole('alert')).toBeInTheDocument();
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// Loading / Empty / Error states
// ═══════════════════════════════════════════════════════════════════════════════

describe('T28: Hypotheses board — loading, empty, and error states', () => {
  test('shows a loading indicator while hypotheses are being fetched', async () => {
    server.use(
      http.get('/api/me', () => HttpResponse.json({ id: 1, email: 'david@example.com', name: 'David', role: 'admin' })),
      http.get('/api/hypotheses', async () => {
        // Delay indefinitely to test loading state
        await new Promise(() => {});
        return HttpResponse.json({ items: [], total: 0 });
      }),
    );

    renderWithProviders(<App />, { route: '/hypotheses' });

    await waitFor(() => {
      expect(
        screen.getByRole('status') || screen.getByLabelText(/loading/i) || screen.getByText(/loading/i),
      ).toBeInTheDocument();
    });
  });

  test('shows an empty state when there are no hypotheses', async () => {
    server.use(
      http.get('/api/me', () => HttpResponse.json({ id: 1, email: 'david@example.com', name: 'David', role: 'admin' })),
      http.get('/api/hypotheses', () => HttpResponse.json({ items: [], total: 0 })),
    );

    renderWithProviders(<App />, { route: '/hypotheses' });

    await waitFor(() => {
      expect(
        screen.getByText(/no hypotheses/i) || screen.getByText(/get started/i) || screen.getByText(/add your first/i),
      ).toBeInTheDocument();
    });
  });

  test('shows an error state when GET /api/hypotheses fails', async () => {
    server.use(
      http.get('/api/me', () => HttpResponse.json({ id: 1, email: 'david@example.com', name: 'David', role: 'admin' })),
      http.get('/api/hypotheses', () => new HttpResponse(null, { status: 500 })),
    );

    renderWithProviders(<App />, { route: '/hypotheses' });

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument();
    });
  });

  test('error state has a retry button that re-fetches hypotheses', async () => {
    let callCount = 0;
    server.use(
      http.get('/api/me', () => HttpResponse.json({ id: 1, email: 'david@example.com', name: 'David', role: 'admin' })),
      http.get('/api/hypotheses', () => {
        callCount++;
        if (callCount <= 1) {
          return new HttpResponse(null, { status: 500 });
        }
        return HttpResponse.json({ items: mockHypotheses, total: mockHypotheses.length });
      }),
    );

    const user = userEvent.setup();
    renderWithProviders(<App />, { route: '/hypotheses' });

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument();
    });

    const retryBtn = screen.getByRole('button', { name: /retry|try again/i });
    await user.click(retryBtn);

    await waitFor(() => {
      expect(screen.getByText(/Enterprise brands will pay/)).toBeInTheDocument();
    });
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// Keyboard accessibility
// ═══════════════════════════════════════════════════════════════════════════════

describe('T28: Hypotheses board — keyboard accessibility', () => {
  test('hypothesis cards are expandable with Enter/Space keyboard interaction', async () => {
    const user = userEvent.setup();
    renderHypothesesPage();

    await waitFor(() => {
      expect(screen.getByText(/Enterprise brands will pay/)).toBeInTheDocument();
    });

    // Tab to the first card heading/button and press Enter
    const cardTrigger = screen.getByText(/Enterprise brands will pay/).closest('button') ||
      screen.getByText(/Enterprise brands will pay/).closest('[role="button"]') ||
      screen.getByText(/Enterprise brands will pay/).closest('[tabindex]');
    expect(cardTrigger).toBeInTheDocument();

    // Focus and press enter
    act(() => {
      cardTrigger!.focus();
    });
    await user.keyboard('{Enter}');

    await waitFor(() => {
      // Evidence should expand
      expect(screen.getAllByText(/supports/i).length).toBeGreaterThan(0);
    });
  });

  test('accept/reject buttons are keyboard accessible (focusable and activatable)', async () => {
    const user = userEvent.setup();
    renderHypothesesPage();

    await waitFor(() => {
      expect(screen.getByText(/Enterprise brands will pay/)).toBeInTheDocument();
    });
    await user.click(screen.getByText(/Enterprise brands will pay/));

    await waitFor(() => {
      expect(screen.getByText(/My intern screenshots suspicious listings/)).toBeInTheDocument();
    });

    const suggestedQuote = screen.getByText(/My intern screenshots suspicious listings/);
    const container = suggestedQuote.closest('[data-status="suggested"]') || suggestedQuote.closest('div');
    const acceptBtn = within(container! as HTMLElement).getByRole('button', { name: /accept|confirm|supports/i });

    // Focus and activate with Space
    act(() => {
      acceptBtn.focus();
    });
    expect(document.activeElement).toBe(acceptBtn);
    await user.keyboard(' ');

    // Should trigger the accept action (same as click)
    await waitFor(() => {
      const updatedContainer = screen.getByText(/My intern screenshots suspicious listings/).closest('[data-status="suggested"]') ||
        screen.getByText(/My intern screenshots suspicious listings/).closest('.suggested');
      expect(updatedContainer).not.toBeInTheDocument();
    });
  });

  test('composer input and button are reachable via Tab navigation', async () => {
    const user = userEvent.setup();
    renderHypothesesPage();

    await waitFor(() => {
      expect(screen.getByPlaceholderText(/falsifiable/i)).toBeInTheDocument();
    });

    const input = screen.getByPlaceholderText(/falsifiable/i);
    const btn = screen.getByRole('button', { name: /add hypothesis/i });

    // Both should be focusable
    act(() => {
      input.focus();
    });
    expect(document.activeElement).toBe(input);

    // Belief -> Segment -> Add hypothesis
    await user.tab();
    expect(document.activeElement).toBe(screen.getByLabelText(/segment \(optional\)/i));
    await user.tab();
    expect(document.activeElement).toBe(btn);
  });

  test('composer can be submitted with Enter key after typing a valid statement', async () => {
    const postSpy = vi.fn();
    server.use(
      http.post('/api/hypotheses', async ({ request }) => {
        const body = (await request.json()) as { statement: string };
        postSpy(body);
        return HttpResponse.json(
          { id: 99, statement: body.statement, status: 'open', created_at: new Date().toISOString(), decided_at: null, rollup: { supports: { confirmed: 0, suggested: 0 }, contradicts: { confirmed: 0, suggested: 0 }, companies_supporting: 0, companies_contradicting: 0, last_evidence_at: null }, verdict_hint: null },
          { status: 201 },
        );
      }),
      ...hypothesesHandlers,
    );

    const user = userEvent.setup();
    renderWithProviders(<App />, { route: '/hypotheses' });

    await waitFor(() => {
      expect(screen.getByPlaceholderText(/falsifiable/i)).toBeInTheDocument();
    });

    const input = screen.getByPlaceholderText(/falsifiable/i);
    await user.type(input, 'Brands care more about speed than coverage{Enter}');

    await waitFor(() => {
      expect(postSpy).toHaveBeenCalledWith(
        expect.objectContaining({ statement: 'Brands care more about speed than coverage' }),
      );
    });
  });

  test('expanded evidence section has appropriate ARIA roles for screen readers', async () => {
    const user = userEvent.setup();
    renderHypothesesPage();

    await waitFor(() => {
      expect(screen.getByText(/Enterprise brands will pay/)).toBeInTheDocument();
    });
    await user.click(screen.getByText(/Enterprise brands will pay/));

    await waitFor(() => {
      // The expandable section should use appropriate aria attributes
      const expandedRegion = screen.getByRole('region') || screen.getByLabelText(/evidence/i);
      expect(expandedRegion).toBeInTheDocument();
    });
  });
});


// ═══════════════════════════════════════════════════════════════════════════════
// T48: evidence-gated intake
// ═══════════════════════════════════════════════════════════════════════════════

describe('T48: evidence-gated hypothesis intake', () => {
  test('Check evidence first shows matched quotes, opt-in confirm, then saves', async () => {
    const user = userEvent.setup();
    renderHypothesesPage();

    const input = await screen.findByPlaceholderText(/state a falsifiable belief/i);
    await user.type(input, 'Customers rely on manual Excel exports to clean listings');
    await user.click(screen.getByRole('button', { name: /check evidence first/i }));

    // The matched quote appears in a confirm panel.
    const panel = await screen.findByTestId('intake-panel');
    expect(within(panel).getByText(/export it to Excel/i)).toBeInTheDocument();

    // The strong match starts ticked, so the button states what will be saved.
    expect(within(panel).getByRole('checkbox', { name: /confirm evidence 501/i })).toBeChecked();
    expect(within(panel).getByRole('button', { name: /save with 1 quote/i })).toBeInTheDocument();
    expect(within(panel).getByText(/match 0\.90/i)).toBeInTheDocument();
    expect(within(panel).getByTestId('band-preview')).toHaveTextContent(/candidate/i);

    // Unticking it flips the button to a hunch save and the preview to Hunch.
    await user.click(within(panel).getByRole('checkbox', { name: /confirm evidence 501/i }));
    expect(within(panel).getByRole('button', { name: /save as hunch/i })).toBeInTheDocument();
    expect(within(panel).getByTestId('band-preview')).toHaveTextContent(/hunch/i);
    await user.click(within(panel).getByRole('checkbox', { name: /confirm evidence 501/i }));
    expect(within(panel).getByRole('button', { name: /save with 1 quote/i })).toBeInTheDocument();

    // Saving closes the panel.
    await user.click(within(panel).getByRole('button', { name: /save with 1 quote/i }));
    await waitFor(() => expect(screen.queryByTestId('intake-panel')).not.toBeInTheDocument());
  });
});


// ═══════════════════════════════════════════════════════════════════════════════
// Hypotheses PRD slice C1: composer segment + scored evidence panel
// ═══════════════════════════════════════════════════════════════════════════════

describe('Hypotheses PRD C1: composer segment + evidence panel', () => {
  const typeBelief = async (user: ReturnType<typeof userEvent.setup>) => {
    const input = await screen.findByPlaceholderText(/state a falsifiable belief/i);
    await user.type(input, 'Customers rely on manual Excel exports to clean listings');
  };

  test('segment field is sent with intake preview and commit', async () => {
    const user = userEvent.setup();
    renderHypothesesPage();
    let previewBody: Record<string, unknown> | null = null;
    let commitBody: Record<string, unknown> | null = null;
    server.use(
      http.post('/api/hypotheses/intake', async ({ request }) => {
        previewBody = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({
          statement: previewBody.statement,
          segment: previewBody.segment ?? null,
          matches: [],
          grounding_preview: 'hunch',
          suggested_questions: [],
        });
      }),
      http.post('/api/hypotheses/intake/commit', async ({ request }) => {
        commitBody = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(
          { id: 1000, statement: commitBody.statement, segment: commitBody.segment, status: 'open', created_at: new Date().toISOString() },
          { status: 201 },
        );
      }),
    );
    await typeBelief(user);
    await user.type(screen.getByLabelText(/segment \(optional\)/i), 'Mid-market');
    await user.click(screen.getByRole('button', { name: /check evidence first/i }));
    const panel = await screen.findByTestId('intake-panel');
    expect(previewBody).toMatchObject({ segment: 'Mid-market' });
    await user.click(within(panel).getByRole('button', { name: /save as hunch/i }));
    await waitFor(() => expect(commitBody).not.toBeNull());
    expect(commitBody).toMatchObject({ segment: 'Mid-market' });
  });

  test('weak matches sit under a divider, start unticked, and show source + score', async () => {
    const user = userEvent.setup();
    renderHypothesesPage();
    server.use(
      http.post('/api/hypotheses/intake', async ({ request }) => {
        const body = (await request.json()) as { statement: string };
        return HttpResponse.json({
          statement: body.statement,
          segment: null,
          matches: [
            { highlight_id: 1, quote: 'Weak one', tag_key: 'pain', conversation_id: 1, relation: 'supports', confidence: 0.62, rationale: 'Loosely related.', strong: false },
            { highlight_id: 2, quote: 'Strong one', tag_key: 'pain', conversation_id: 1, relation: 'supports', confidence: 0.91, rationale: 'Direct.', strong: true, company_name: 'Acme Watches', contact_name: 'Maria', conversation_date: '2026-03-02' },
          ],
          grounding_preview: 'grounded',
          suggested_questions: ['When did you last do this?'],
        });
      }),
    );
    await typeBelief(user);
    await user.click(screen.getByRole('button', { name: /check evidence first/i }));
    const panel = await screen.findByTestId('intake-panel');
    expect(within(panel).getByText(/weaker matches/i)).toBeInTheDocument();
    expect(within(panel).getByRole('checkbox', { name: /confirm evidence 2/i })).toBeChecked();
    expect(within(panel).getByRole('checkbox', { name: /confirm evidence 1/i })).not.toBeChecked();
    expect(within(panel).getByText(/Acme Watches · Maria · 2026-03-02/)).toBeInTheDocument();
    expect(within(panel).getByText(/ask next to test it/i)).toBeInTheDocument();
    expect(within(panel).getByRole('button', { name: /save with 1 quote/i })).toBeInTheDocument();
  });

  test('a failed evidence check keeps the belief and offers Save as hunch', async () => {
    const user = userEvent.setup();
    renderHypothesesPage();
    server.use(http.post('/api/hypotheses/intake', () => new HttpResponse(null, { status: 500 })));
    await typeBelief(user);
    await user.click(screen.getByRole('button', { name: /check evidence first/i }));
    expect(await screen.findByText(/couldn.t check the evidence/i)).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/state a falsifiable belief/i)).toHaveValue(
      'Customers rely on manual Excel exports to clean listings',
    );
    expect(screen.getByRole('button', { name: /^save as hunch$/i })).toBeInTheDocument();
  });
});


// ═══════════════════════════════════════════════════════════════════════════════
// Hypotheses PRD slice C2/C3: grounding-band board, filters, detail, archive
// ═══════════════════════════════════════════════════════════════════════════════

describe('Hypotheses PRD C2/C3: grounding-band board', () => {
  const mk = (
    id: number,
    statement: string,
    grounding: string,
    over: Partial<{ segment: string | null; supC: number; supS: number; conC: number; pending: number; freshness: string }> = {},
  ) => ({
    id,
    statement,
    segment: over.segment ?? null,
    status: 'open',
    created_by: 1,
    created_at: '2026-08-01T00:00:00Z',
    decided_at: null,
    rollup: {
      supports: { confirmed: over.supC ?? 0, suggested: over.supS ?? 0 },
      contradicts: { confirmed: over.conC ?? 0, suggested: 0 },
      companies_supporting: over.supC ? 2 : 0,
      companies_contradicting: over.conC ? 1 : 0,
      last_evidence_at: null,
      freshness: over.freshness ?? 'fresh',
      newest_evidence_at: over.supC ? '2026-07-30' : null,
      grounding,
      pending_count: over.pending ?? 0,
      grounding_reason: `Reason for ${statement}`,
    },
    verdict_hint: null,
  });

  const list = [
    mk(11, 'Alpha grounded belief about ops teams', 'grounded', { segment: 'Mid-market', supC: 3, freshness: 'stale' }),
    mk(12, 'Bravo contested belief about pricing', 'contested', { segment: 'Enterprise', supC: 2, conC: 2 }),
    mk(13, 'Charlie candidate belief about exports', 'candidate', { segment: 'Mid-market', supS: 2, pending: 2 }),
    mk(14, 'Delta hunch belief about onboarding', 'hunch'),
    mk(15, 'Echo refuted belief about coverage', 'refuted', { conC: 3 }),
  ];

  const renderBoard = (items = list) => {
    server.use(
      http.get('/api/hypotheses', () => HttpResponse.json({ items, total: items.length })),
      http.get('/api/hypotheses/:id', ({ params }) => {
        const item = items.find((i) => String(i.id) === params.id);
        return item
          ? HttpResponse.json({ ...item, evidence: { supports: [], contradicts: [] } })
          : new HttpResponse(null, { status: 404 });
      }),
    );
    return renderWithProviders(<App />, { route: '/hypotheses' });
  };

  test('renders one column per grounding band with counts and the right cards', async () => {
    renderBoard();
    const grounded = await screen.findByRole('group', { name: /^grounded hypotheses$/i });
    expect(within(grounded).getByText(/Alpha grounded/)).toBeInTheDocument();
    expect(within(grounded).getByText('Mid-market')).toBeInTheDocument();
    expect(within(grounded).getByText('Stale')).toBeInTheDocument();
    for (const [name, text] of [
      ['contested', /Bravo contested/],
      ['candidate', /Charlie candidate/],
      ['hunch', /Delta hunch/],
      ['refuted', /Echo refuted/],
    ] as const) {
      const col = screen.getByRole('group', { name: new RegExp(`^${name} hypotheses$`, 'i') });
      expect(within(col).getByText(text)).toBeInTheDocument();
      expect(within(col).getByRole('heading', { name: new RegExp(name, 'i') })).toBeInTheDocument();
    }
    // Header counts
    expect(within(grounded).getByText('1')).toBeInTheDocument();
  });

  test('filters by segment, band and pending suggestions', async () => {
    const user = userEvent.setup();
    renderBoard();
    await screen.findByText(/Alpha grounded/);

    await user.selectOptions(screen.getByLabelText(/^segment$/i), 'Mid-market');
    expect(screen.getByText(/Alpha grounded/)).toBeInTheDocument();
    expect(screen.getByText(/Charlie candidate/)).toBeInTheDocument();
    expect(screen.queryByText(/Bravo contested/)).not.toBeInTheDocument();

    await user.click(screen.getByLabelText(/has pending suggestions/i));
    expect(screen.getByText(/Charlie candidate/)).toBeInTheDocument();
    expect(screen.queryByText(/Alpha grounded/)).not.toBeInTheDocument();

    await user.click(screen.getByLabelText(/has pending suggestions/i));
    await user.selectOptions(screen.getByLabelText(/^segment$/i), '');
    await user.selectOptions(screen.getByLabelText(/^band$/i), 'refuted');
    expect(screen.getByText(/Echo refuted/)).toBeInTheDocument();
    expect(screen.queryByText(/Alpha grounded/)).not.toBeInTheDocument();
  });

  test('opening a card shows the band, the grounding reason and an Archive action', async () => {
    const user = userEvent.setup();
    renderBoard();
    await user.click(await screen.findByText(/Bravo contested/));
    const detail = await screen.findByTestId('hypothesis-detail');
    expect(within(detail).getByTestId('grounding-reason')).toHaveTextContent(/Reason for Bravo contested/);
    expect(within(detail).getByText('Contested')).toBeInTheDocument();
    expect(within(detail).getByRole('button', { name: /archive/i })).toBeInTheDocument();
  });

  test('Archive PATCHes status=archived and removes the card from the board', async () => {
    let patched: Record<string, unknown> | null = null;
    server.use(
      http.patch('/api/hypotheses/:id', async ({ request }) => {
        patched = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ id: 14, statement: 'Delta hunch belief about onboarding', segment: null, status: 'archived', created_at: '2026-08-01T00:00:00Z', decided_at: null });
      }),
    );
    const user = userEvent.setup();
    renderBoard();
    await user.click(await screen.findByText(/Delta hunch/));
    const detail = await screen.findByTestId('hypothesis-detail');
    await user.click(within(detail).getByRole('button', { name: /archive/i }));
    await waitFor(() => expect(screen.queryByText(/Delta hunch/)).not.toBeInTheDocument());
    expect(patched).toMatchObject({ status: 'archived' });
  });
});


// ═══════════════════════════════════════════════════════════════════════════════
// Hypotheses PRD: detail panel — edit, questions, history, add evidence, cite
// ═══════════════════════════════════════════════════════════════════════════════

describe('Hypotheses PRD: detail panel features', () => {
  const baseItem = (over: Record<string, unknown> = {}) => ({
    id: 21,
    statement: 'Foxtrot belief about renewal timing patterns',
    segment: 'SMB',
    status: 'open',
    created_by: 1,
    created_at: '2026-08-01T00:00:00Z',
    decided_at: null,
    rollup: {
      supports: { confirmed: 1, suggested: 0 },
      contradicts: { confirmed: 0, suggested: 0 },
      companies_supporting: 1,
      companies_contradicting: 0,
      last_evidence_at: null,
      freshness: 'fresh',
      newest_evidence_at: '2026-07-30',
      grounding: 'grounded',
      pending_count: 0,
      grounding_reason: '1 supporting quote from 1 company, 0 contradicting.',
    },
    verdict_hint: null,
    ...over,
  });

  const evidenceLink = {
    link_id: 301, highlight_id: 77, quote: 'We renew only after the pilot', conversation_id: 1,
    conversation_title: 'Call', utterance_id: 3, company_name: 'Acme', contact_name: 'Maria',
    confidence: 0.9, origin: 'ai', status: 'confirmed', rationale: null,
  };

  const setup = (detailOver: Record<string, unknown> = {}) => {
    const calls: Record<string, unknown[]> = { patch: [], question: [], link: [] };
    server.use(
      http.get('/api/hypotheses', () => HttpResponse.json({ items: [baseItem()], total: 1 })),
      http.get('/api/hypotheses/segments', () => HttpResponse.json({ items: ['Enterprise', 'SMB'] })),
      http.get('/api/hypotheses/21', () =>
        HttpResponse.json({
          ...baseItem(),
          evidence: { supports: [evidenceLink], contradicts: [] },
          questions: [
            { id: 1, text: 'When did you last renew?', asked_at: null },
            { id: 2, text: 'Who signs off?', asked_at: '2026-08-02T00:00:00Z' },
          ],
          ...detailOver,
        }),
      ),
      http.get('/api/hypotheses/21/history', () =>
        HttpResponse.json({
          items: [
            { id: 2, from_band: 'candidate', to_band: 'grounded', cause_link_id: 301, cause_quote: 'We renew only after the pilot', cause_stance: 'supports', created_at: '2026-08-03T00:00:00Z' },
            { id: 1, from_band: null, to_band: 'hunch', cause_link_id: null, cause_quote: null, cause_stance: null, created_at: '2026-08-01T00:00:00Z' },
          ],
        }),
      ),
      http.patch('/api/hypotheses/21', async ({ request }) => {
        calls.patch.push(await request.json());
        return HttpResponse.json({ ...baseItem(), segment: 'Mid-market' });
      }),
      http.patch('/api/hypotheses/21/questions/:qid', async ({ request, params }) => {
        calls.question.push({ qid: params.qid, ...((await request.json()) as object) });
        return HttpResponse.json({ id: Number(params.qid), text: 'x', asked_at: '2026-08-04T00:00:00Z' });
      }),
      http.get('/api/highlights', ({ request }) => {
        const q = new URL(request.url).searchParams.get('q') ?? '';
        const all = [
          { id: 77, conversation_id: 1, utterance_id: 3, tag_key: 'pain', quote: 'We renew only after the pilot', confidence: 0.9, status: 'accepted', origin: 'ai', conversation_title: 'Call', conversation_happened_at: null, company_name: 'Acme', contact_names: ['Maria'] },
          { id: 88, conversation_id: 2, utterance_id: 4, tag_key: 'pain', quote: 'Renewals slip because of procurement', confidence: 0.8, status: 'accepted', origin: 'ai', conversation_title: 'Call 2', conversation_happened_at: null, company_name: 'Globex', contact_names: ['Sam'] },
        ].filter((h) => h.quote.toLowerCase().includes(q.toLowerCase()));
        return HttpResponse.json({ items: all, total: all.length, limit: 8, offset: 0 });
      }),
      http.post('/api/hypotheses/21/links', async ({ request }) => {
        calls.link.push(await request.json());
        return HttpResponse.json({ id: 999, status: 'confirmed' }, { status: 201 });
      }),
    );
    return calls;
  };

  const open = async (user: ReturnType<typeof userEvent.setup>) => {
    renderWithProviders(<App />, { route: '/hypotheses' });
    await user.click(await screen.findByText(/Foxtrot belief/));
    return screen.findByTestId('hypothesis-detail');
  };

  test('shows validation questions with asked state and toggles via the API', async () => {
    const calls = setup();
    const user = userEvent.setup();
    const detail = await open(user);
    const q1 = await within(detail).findByRole('checkbox', { name: /mark asked: when did you last renew/i });
    expect(q1).not.toBeChecked();
    expect(within(detail).getByRole('checkbox', { name: /mark asked: who signs off/i })).toBeChecked();
    await user.click(q1);
    await waitFor(() => expect(calls.question).toEqual([{ qid: '1', asked: true }]));
  });

  test('shows band history with the quote that caused each change', async () => {
    setup();
    const user = userEvent.setup();
    const detail = await open(user);
    const history = await within(detail).findByRole('region', { name: /band history/i });
    expect(within(history).getByText(/added as/i)).toBeInTheDocument();
    expect(within(history).getByText(/supported by/i)).toHaveTextContent(/We renew only after the pilot/);
  });

  test('inline edit saves a changed segment; statement is locked once evidence is linked', async () => {
    const calls = setup();
    const user = userEvent.setup();
    const detail = await open(user);
    await within(detail).findByRole('button', { name: /^edit$/i });
    await user.click(within(detail).getByRole('button', { name: /^edit$/i }));
    const form = within(detail).getByRole('form', { name: /edit hypothesis/i });
    expect(within(form).getByLabelText(/^belief$/i)).toBeDisabled();
    const seg = within(form).getByLabelText(/^segment$/i);
    await user.clear(seg);
    await user.type(seg, 'Mid-market');
    await user.click(within(form).getByRole('button', { name: /save changes/i }));
    await waitFor(() => expect(calls.patch).toEqual([{ segment: 'Mid-market' }]));
  });

  test('Add evidence searches quotes, hides already-linked ones, and links with a stance', async () => {
    const calls = setup();
    const user = userEvent.setup();
    const detail = await open(user);
    await user.click(await within(detail).findByRole('button', { name: /^add evidence$/i }));
    await user.type(within(detail).getByLabelText(/search quotes/i), 'renew');
    // 77 is already linked -> only 88 is offered
    await within(detail).findByText(/Renewals slip because of procurement/);
    expect(within(detail).queryByText(/We renew only after the pilot.*Supports/)).not.toBeInTheDocument();
    await user.click(within(detail).getByRole('button', { name: /link as contradicts: renewals slip/i }));
    await waitFor(() =>
      expect(calls.link).toEqual([{ highlight_id: 88, stance: 'contradicts', confirm: true }]),
    );
  });

  test('Cite in decision links to Decisions prefilled with the hypothesis and confirmed quotes', async () => {
    setup();
    const user = userEvent.setup();
    const detail = await open(user);
    const link = await within(detail).findByRole('link', { name: /cite in decision/i });
    expect(link).toHaveAttribute('href', '/decisions?hypothesis_id=21&highlight_id=77');
  });

  test('composer segment suggestions come from /hypotheses/segments', async () => {
    setup();
    renderWithProviders(<App />, { route: '/hypotheses' });
    await screen.findByText(/Foxtrot belief/);
    await waitFor(() => {
      const options = Array.from(document.querySelectorAll('#hypothesis-segments option')).map((o) => o.getAttribute('value'));
      expect(options).toEqual(['Enterprise', 'SMB']);
    });
  });
});


describe('Hypotheses PRD: band rules in the UI', () => {
  test('composer previews Grounded only once 3 ticked supports span 2 companies', async () => {
    const user = userEvent.setup();
    renderHypothesesPage();
    server.use(
      http.post('/api/hypotheses/intake', async ({ request }) => {
        const body = (await request.json()) as { statement: string };
        const m = (id: number, company: string) => ({
          highlight_id: id, quote: `Quote ${id}`, tag_key: 'pain', conversation_id: id,
          relation: 'supports', confidence: 0.9, rationale: 'r', strong: true, company_name: company,
        });
        return HttpResponse.json({
          statement: body.statement, segment: null,
          matches: [m(1, 'Acme'), m(2, 'Acme'), m(3, 'Northwind')],
          grounding_preview: 'grounded', suggested_questions: [],
        });
      }),
    );
    await user.type(
      await screen.findByPlaceholderText(/state a falsifiable belief/i),
      'Customers rely on manual Excel exports to clean listings',
    );
    await user.click(screen.getByRole('button', { name: /check evidence first/i }));
    const panel = await screen.findByTestId('intake-panel');
    expect(within(panel).getByTestId('band-preview')).toHaveTextContent(/grounded/i);
    // Drop the only Northwind quote: 2 supports, 1 company -> Candidate.
    await user.click(within(panel).getByRole('checkbox', { name: /confirm evidence 3/i }));
    expect(within(panel).getByTestId('band-preview')).toHaveTextContent(/candidate/i);
    await user.click(within(panel).getByRole('checkbox', { name: /confirm evidence 1/i }));
    await user.click(within(panel).getByRole('checkbox', { name: /confirm evidence 2/i }));
    expect(within(panel).getByTestId('band-preview')).toHaveTextContent(/hunch/i);
  });

  test('"How bands work" lists the live rules', async () => {
    const user = userEvent.setup();
    renderHypothesesPage();
    const help = await screen.findByTestId('band-rules-help');
    await user.click(within(help).getByText(/how bands work/i));
    expect(within(help).getByText(/3\+ confirmed supporting quotes from 2\+ companies/)).toBeInTheDocument();
    expect(within(help).getByText(/suggested matches wait for your review/i)).toBeInTheDocument();
  });
});
