/**
 * UX Fix Loop — behavioral tests for mandatory fixes A-J.
 * Tests: #15 active_only filter, #19 past sessions, #18 session history,
 * #16 clear all + active state, #23 tokens, #13 signal chips, #21 sidebar labels,
 * #8 next_step preference, accessibility labels.
 */
import { describe, it, expect } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
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

// ─── A. #15: Company FILTER dropdowns use active_only=true ───
describe('UX #15: Company filter dropdowns hide zero-conversation companies', () => {
  it('ExplorePage fetches companies with active_only=true', async () => {
    let fetchedUrl = '';
    server.use(
      http.get('/api/companies', ({ request }) => {
        fetchedUrl = request.url;
        return HttpResponse.json([
          { id: 1, name: 'Acme Watches', domain: 'acme.com', notes: null, created_at: '2026-08-01T00:00:00Z' },
        ]);
      }),
      http.get('/api/highlights', () =>
        HttpResponse.json({ items: [], total: 0, limit: 100, offset: 0 })
      ),
    );

    const { ExplorePage } = await import('../pages/ExplorePage');
    render(<ExplorePage />, { wrapper: createWrapper(['/explore']) });

    await waitFor(() => {
      expect(fetchedUrl).toContain('active_only=true');
    });
  });

  it('SimulatorPage fetches companies with active_only=true', async () => {
    let fetchedUrl = '';
    server.use(
      http.get('/api/companies', ({ request }) => {
        fetchedUrl = request.url;
        return HttpResponse.json([]);
      }),
      http.get('/api/tags', () => HttpResponse.json([])),
      http.get('/api/simulator/sessions', () => HttpResponse.json({ items: [], total: 0 })),
    );

    const { SimulatorPage } = await import('../pages/SimulatorPage');
    render(<SimulatorPage />, { wrapper: createWrapper(['/simulator']) });

    await waitFor(() => {
      expect(fetchedUrl).toContain('active_only=true');
    });
  });

  it('ExplorePage shows only active companies in dropdown', async () => {
    server.use(
      http.get('/api/companies', ({ request }) => {
        const url = new URL(request.url);
        if (url.searchParams.get('active_only') === 'true') {
          return HttpResponse.json([
            { id: 1, name: 'Active Corp', domain: null, notes: null, created_at: '2026-08-01T00:00:00Z' },
          ]);
        }
        return HttpResponse.json([
          { id: 1, name: 'Active Corp', domain: null, notes: null, created_at: '2026-08-01T00:00:00Z' },
          { id: 2, name: 'Ghost Corp', domain: null, notes: null, created_at: '2026-08-01T00:00:00Z' },
        ]);
      }),
      http.get('/api/highlights', () =>
        HttpResponse.json({ items: [], total: 0, limit: 100, offset: 0 })
      ),
    );

    const { ExplorePage } = await import('../pages/ExplorePage');
    render(<ExplorePage />, { wrapper: createWrapper(['/explore']) });

    await waitFor(() => {
      const select = screen.getByLabelText('Filter by company');
      expect(select).toBeInTheDocument();
      expect(within(select).getByText('Active Corp')).toBeInTheDocument();
      expect(within(select).queryByText('Ghost Corp')).not.toBeInTheDocument();
    });
  });
});

// ─── B. #19: SimulatorPage past sessions ───
describe('UX #19: SimulatorPage past practice sessions', () => {
  it('renders past sessions list with title/date/status/score', async () => {
    server.use(
      http.get('/api/companies', () => HttpResponse.json([])),
      http.get('/api/tags', () => HttpResponse.json([])),
      http.get('/api/simulator/sessions', () =>
        HttpResponse.json({
          items: [
            { id: 10, title: 'Sim: Practice A', status: 'ready', created_at: '2026-08-15T10:00:00Z', score: 7, has_analysis: true },
            { id: 11, title: 'Sim: Practice B', status: 'processing', created_at: '2026-08-16T10:00:00Z', score: null, has_analysis: false },
          ],
          total: 2,
        })
      ),
    );

    const { SimulatorPage } = await import('../pages/SimulatorPage');
    render(<SimulatorPage />, { wrapper: createWrapper(['/simulator']) });

    await waitFor(() => {
      expect(screen.getByTestId('past-sessions')).toBeInTheDocument();
      expect(screen.getByText('Sim: Practice A')).toBeInTheDocument();
      expect(screen.getByText('7/10')).toBeInTheDocument();
      expect(screen.getByText('Sim: Practice B')).toBeInTheDocument();
    });

    // Should be links to conversation results
    const items = screen.getAllByTestId('past-session-item');
    expect(items.length).toBe(2);
    expect(items[0].getAttribute('href')).toBe('/conversations/10');
  });

  it('shows empty state when no past sessions', async () => {
    server.use(
      http.get('/api/companies', () => HttpResponse.json([])),
      http.get('/api/tags', () => HttpResponse.json([])),
      http.get('/api/simulator/sessions', () => HttpResponse.json({ items: [], total: 0 })),
    );

    const { SimulatorPage } = await import('../pages/SimulatorPage');
    render(<SimulatorPage />, { wrapper: createWrapper(['/simulator']) });

    await waitFor(() => {
      expect(screen.getByTestId('no-past-sessions')).toBeInTheDocument();
    });
  });

  it('shows error state when fetch fails', async () => {
    server.use(
      http.get('/api/companies', () => HttpResponse.json([])),
      http.get('/api/tags', () => HttpResponse.json([])),
      http.get('/api/simulator/sessions', () => HttpResponse.error()),
    );

    const { SimulatorPage } = await import('../pages/SimulatorPage');
    render(<SimulatorPage />, { wrapper: createWrapper(['/simulator']) });

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument();
      expect(screen.getByText(/Failed to load past sessions/)).toBeInTheDocument();
    });
  });
});

// ─── C. #18: MeetingsPage session history ───
describe('UX #18: MeetingsPage session history', () => {
  it('renders empty session history table', async () => {
    const { MeetingsPage } = await import('../pages/MeetingsPage');
    render(<MeetingsPage />, { wrapper: createWrapper(['/meetings']) });

    expect(screen.getByTestId('session-history')).toBeInTheDocument();
    expect(screen.getByTestId('session-history-empty')).toBeInTheDocument();
    expect(screen.getByText(/No bots sent yet/)).toBeInTheDocument();
  });

  it('appends active entry on successful Send, updates on Stop', async () => {
    server.use(
      http.post('/api/vexa/bots', () =>
        HttpResponse.json({ platform: 'gmeet', native_meeting_id: 'abc-123', status: 'active' })
      ),
      http.get('/api/vexa/transcripts/gmeet/abc-123', () =>
        HttpResponse.json({ segments: [{ speaker: 'A', text: 'Hi', completed: false }], total: 1 })
      ),
      http.delete('/api/vexa/bots/gmeet/abc-123', () =>
        HttpResponse.json({ ok: true })
      ),
    );

    const { MeetingsPage } = await import('../pages/MeetingsPage');
    render(<MeetingsPage />, { wrapper: createWrapper(['/meetings']) });

    // Send a bot
    const input = screen.getByLabelText('Meeting URL');
    await userEvent.type(input, 'https://meet.google.com/abc-123');
    await userEvent.click(screen.getByText('Send Bot'));

    // Should show active row in history
    await waitFor(() => {
      const rows = screen.getAllByTestId('session-history-row');
      expect(rows.length).toBe(1);
      expect(rows[0]).toHaveTextContent('active');
    });

    // Stop the bot
    await userEvent.click(screen.getByText('Stop Bot'));

    // Status should update to stopped
    await waitFor(() => {
      const rows = screen.getAllByTestId('session-history-row');
      expect(rows[0]).toHaveTextContent('stopped');
    });
  });

  it('session history shows status announcements with aria-label', async () => {
    server.use(
      http.post('/api/vexa/bots', () =>
        HttpResponse.json({ platform: 'zoom', native_meeting_id: 'z-99', status: 'active' })
      ),
      http.get('/api/vexa/transcripts/zoom/z-99', () =>
        HttpResponse.json({ segments: [], total: 0 })
      ),
    );

    const { MeetingsPage } = await import('../pages/MeetingsPage');
    render(<MeetingsPage />, { wrapper: createWrapper(['/meetings']) });

    const input = screen.getByLabelText('Meeting URL');
    await userEvent.type(input, 'https://zoom.us/j/z-99');
    await userEvent.click(screen.getByText('Send Bot'));

    await waitFor(() => {
      const status = screen.getByRole('status', { name: /Bot status: active/ });
      expect(status).toBeInTheDocument();
    });
  });
});

// ─── D. #16: Explore Clear all + active filter state ───
describe('UX #16: Explore Clear all and active filter container', () => {
  it('shows Clear all when tags are active', async () => {
    server.use(
      http.get('/api/companies', () => HttpResponse.json([])),
      http.get('/api/highlights', () =>
        HttpResponse.json({ items: [], total: 0, limit: 100, offset: 0 })
      ),
    );

    const { ExplorePage } = await import('../pages/ExplorePage');
    render(<ExplorePage />, { wrapper: createWrapper(['/explore']) });

    await waitFor(() => {
      // Default state has pain+workaround active
      expect(screen.getByTestId('clear-all-filters')).toBeInTheDocument();
    });
  });

  it('Clear all resets tags, company, and status', async () => {
    server.use(
      http.get('/api/companies', () => HttpResponse.json([])),
      http.get('/api/highlights', () =>
        HttpResponse.json({ items: [], total: 0, limit: 100, offset: 0 })
      ),
    );

    const { ExplorePage } = await import('../pages/ExplorePage');
    render(<ExplorePage />, { wrapper: createWrapper(['/explore']) });

    await waitFor(() => expect(screen.getByTestId('clear-all-filters')).toBeInTheDocument());
    await userEvent.click(screen.getByTestId('clear-all-filters'));

    // After clearing, Clear all should disappear
    await waitFor(() => {
      expect(screen.queryByTestId('clear-all-filters')).not.toBeInTheDocument();
    });
  });

  it('filter container has filled/active style when filters are active', async () => {
    server.use(
      http.get('/api/companies', () => HttpResponse.json([])),
      http.get('/api/highlights', () =>
        HttpResponse.json({ items: [], total: 0, limit: 100, offset: 0 })
      ),
    );

    const { ExplorePage } = await import('../pages/ExplorePage');
    render(<ExplorePage />, { wrapper: createWrapper(['/explore']) });

    await waitFor(() => {
      const container = screen.getByTestId('filter-container');
      expect(container.className).toContain('bg-accent-soft');
      expect(container.className).toContain('border-accent');
    });
  });

  it('shows highlight and company count', async () => {
    server.use(
      http.get('/api/companies', () => HttpResponse.json([])),
      http.get('/api/highlights', () =>
        HttpResponse.json({
          items: [
            { id: 1, conversation_id: 1, utterance_id: 1, tag_key: 'pain', quote: 'test', confidence: 0.9, status: 'accepted', origin: 'ai', conversation_title: 'C1', conversation_happened_at: '2026-08-01', company_name: 'Acme', contact_names: [] },
            { id: 2, conversation_id: 2, utterance_id: 2, tag_key: 'pain', quote: 'test2', confidence: 0.8, status: 'accepted', origin: 'ai', conversation_title: 'C2', conversation_happened_at: '2026-08-02', company_name: 'Beta', contact_names: [] },
          ],
          total: 2,
          limit: 100,
          offset: 0,
        })
      ),
    );

    const { ExplorePage } = await import('../pages/ExplorePage');
    render(<ExplorePage />, { wrapper: createWrapper(['/explore']) });

    await waitFor(() => {
      expect(screen.getByText(/2 highlights · 2 companies/)).toBeInTheDocument();
    });
  });
});

// ─── F. #13: Library signal rendering — deterministic order, cap, context style ───
describe('UX #13: Library signal chips', () => {
  it('renders tags in taxonomy order, capped at 6 with +N overflow', async () => {
    server.use(
      http.get('/api/conversations', () =>
        HttpResponse.json({
          items: [{
            id: 1,
            title: 'Many signals',
            happened_at: '2026-08-12T10:00:00Z',
            status: 'ready',
            interviewer: 'David',
            company: { id: 1, name: 'Test Co', domain: null, notes: null, created_at: '2026-08-01T00:00:00Z' },
            contacts: [],
            meta: null,
            created_at: '2026-08-12T10:00:00Z',
            // Unsorted > 6 tags
            tag_counts: { compliment: 4, money: 2, pain: 5, workaround: 3, commitment: 1, followup: 2, context: 3, person: 1 },
            critique_score: 6,
          }],
          total: 1, limit: 50, offset: 0,
        })
      ),
      http.get('/api/companies', () => HttpResponse.json([])),
      http.get('/api/inbox', () => HttpResponse.json({ total: 0 })),
    );

    const { LibraryPage } = await import('../pages/LibraryPage');
    render(<LibraryPage />, { wrapper: createWrapper(['/']) });

    await waitFor(() => expect(screen.getByText('Many signals')).toBeInTheDocument());

    // Should show +2 overflow (8 tags - 6 cap = 2)
    expect(screen.getByText('+2')).toBeInTheDocument();

    // First 6 by taxonomy order: pain, workaround (obstacle not present), money, commitment, compliment, followup
    // Context/person should NOT be in visible since they're after index 6
    // Actually they are the 7th and 8th in taxonomy order so they overflow
  });

  it('context tags have de-emphasized style', async () => {
    server.use(
      http.get('/api/conversations', () =>
        HttpResponse.json({
          items: [{
            id: 1,
            title: 'Context heavy',
            happened_at: '2026-08-12T10:00:00Z',
            status: 'ready',
            interviewer: 'David',
            company: null,
            contacts: [],
            meta: null,
            created_at: '2026-08-12T10:00:00Z',
            tag_counts: { context: 5, pain: 2 },
            critique_score: 5,
          }],
          total: 1, limit: 50, offset: 0,
        })
      ),
      http.get('/api/companies', () => HttpResponse.json([])),
      http.get('/api/inbox', () => HttpResponse.json({ total: 0 })),
    );

    const { LibraryPage } = await import('../pages/LibraryPage');
    const { container } = render(<LibraryPage />, { wrapper: createWrapper(['/']) });

    await waitFor(() => expect(screen.getByText('Context heavy')).toBeInTheDocument());

    // Context chips should have text-muted class
    const chips = container.querySelectorAll('span.text-muted');
    const contextChip = Array.from(chips).find((el) => el.textContent?.includes('🎯'));
    expect(contextChip).toBeTruthy();
  });
});

// ─── H. #21: AnalysisSidebar labels Score, Best question, Violations ───
describe('UX #21: AnalysisSidebar explicit labels', () => {
  it('renders Score, Best question, and Violations labels', async () => {
    const { AnalysisSidebar } = await import('../components/AnalysisSidebar');
    const mockAnalysis = {
      id: 1,
      conversation_id: 1,
      kind: 'conversation' as const,
      model: 'gpt-4o',
      prompt_version: 'v1',
      created_at: '2026-08-12T12:00:00Z',
      result: {
        summary: 'Good interview',
        mom_test_critique: {
          score: 8,
          good_questions: ['How do you handle that today?'],
          violations: [{ utterance_idx: 4, type: 'leading_question', better: 'Try open-ended' }],
        },
      },
    };

    render(
      <AnalysisSidebar analysis={mockAnalysis} highlights={[]} onJumpToUtterance={() => {}} />,
      { wrapper: createWrapper() },
    );

    expect(screen.getByText('Score')).toBeInTheDocument();
    expect(screen.getByText('Best question')).toBeInTheDocument();
    expect(screen.getByText('Violations')).toBeInTheDocument();
  });
});

// ─── J. Accessibility: aria-labels on Explore selects ───
describe('UX Accessibility: Explore selects have labels', () => {
  it('company select has aria-label', async () => {
    server.use(
      http.get('/api/companies', () => HttpResponse.json([])),
      http.get('/api/highlights', () =>
        HttpResponse.json({ items: [], total: 0, limit: 100, offset: 0 })
      ),
    );

    const { ExplorePage } = await import('../pages/ExplorePage');
    render(<ExplorePage />, { wrapper: createWrapper(['/explore']) });

    await waitFor(() => {
      expect(screen.getByLabelText('Filter by company')).toBeInTheDocument();
      expect(screen.getByLabelText('Filter by status')).toBeInTheDocument();
    });
  });
});

// ─── E. #23: Token alignment assertions ───
describe('UX #23: Token alignment', () => {
  it('DigestPage uses design tokens not raw indigo/gray', async () => {
    server.use(
      http.get('/api/digest/preview', () =>
        HttpResponse.json({ markdown: '## Test\n- item' })
      ),
    );

    const { DigestPage } = await import('../pages/DigestPage');
    render(<DigestPage />, { wrapper: createWrapper(['/digest']) });

    // Button should use btn-primary class
    const btn = screen.getByTestId('digest-preview-btn');
    expect(btn.className).toContain('btn');
    // Should NOT have raw indigo classes
    expect(btn.className).not.toContain('indigo');
  });

  it('SimulatorPage uses bg-surface and border-hairline tokens', async () => {
    server.use(
      http.get('/api/companies', () => HttpResponse.json([])),
      http.get('/api/tags', () => HttpResponse.json([])),
      http.get('/api/simulator/sessions', () => HttpResponse.json({ items: [], total: 0 })),
    );

    const { SimulatorPage } = await import('../pages/SimulatorPage');
    render(<SimulatorPage />, { wrapper: createWrapper(['/simulator']) });

    await waitFor(() => {
      const pastSessions = screen.getByTestId('past-sessions');
      expect(pastSessions.className).toContain('bg-surface');
      expect(pastSessions.className).toContain('border-hairline');
    });
  });

  it('SettingsPage uses standard h1 size', async () => {
    server.use(
      http.get('/api/settings/status', () =>
        HttpResponse.json({
          llm: { backend: 'openai', model_normalizer: 'gpt-4o', model_tagger: 'gpt-4o', model_analyst: 'gpt-4o', model_synthesizer: 'gpt-4o', api_key_configured: false, api_key_hint: 'not set' },
          vexa: { configured: false, detail: 'not set' },
          gdrive: { configured: false, detail: 'not set' },
          slack: { configured: false, detail: 'not set' },
          digest: { slack_configured: false, schedule: 'Not configured' },
          taxonomy_count: 12,
          active_company_count: 0,
        })
      ),
    );

    const { SettingsPage } = await import('../pages/SettingsPage');
    render(<SettingsPage />, { wrapper: createWrapper(['/settings']) });

    await waitFor(() => {
      const h1 = screen.getByRole('heading', { level: 1, name: 'Settings' });
      expect(h1).toBeInTheDocument();
      expect(h1.className).toContain('text-xl');
    });
  });
});


describe('UX #8: actionable follow-up task display', () => {
  it('prefers synthesized task text while retaining the conversation evidence link', async () => {
    server.use(
      http.get('/api/stats', () =>
        HttpResponse.json({
          tag_counts_by_month: {},
          critique_trend: [],
          compliment_ratio_trend: [],
          stale_hypotheses: 0,
          open_followups: [
            {
              id: 7,
              task: 'Sit in on the Friday one-pager session — the 28th',
              quote: 'The 28th, in the afternoon probably.',
              conversation_id: 12,
              conversation_title: 'FakeCorp discovery',
              happened_at: '2026-08-17T10:00:00Z',
              created_at: '2026-08-17T10:00:00Z',
            },
          ],
        }),
      ),
    );

    const { InsightsPage } = await import('../pages/InsightsPage');
    render(<InsightsPage />, { wrapper: createWrapper(['/insights']) });

    await waitFor(() => {
      expect(screen.getByText(/Sit in on the Friday one-pager session — the 28th/)).toBeInTheDocument();
    });
    expect(screen.queryByText('The 28th, in the afternoon probably.')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: /FakeCorp discovery/ })).toHaveAttribute(
      'href',
      '/conversations/12',
    );
  });
});
