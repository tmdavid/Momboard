/** MCP PRD: the links tools hand to Claude land on the thing they cite. */
import { describe, expect, test } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { server } from '../test/mocks/server';
import { renderWithProviders } from '../test/render';
import { App } from '../App';

const synthesis = (id: number, theme: string) => ({
  id, kind: 'synthesis', input_scope: { tags: ['pain'] }, model: 'm', prompt_version: 'v', saved: true, status: 'ready',
  created_at: '2026-11-0' + id + 'T09:00:00Z', error: null,
  result: { themes: [{ name: theme, summary: 'Because.', evidence_highlight_ids: [], strength: 'high' }], contradictions: [], validate_next: [] },
});

describe('Quote link: /conversations/:id?highlight=:id', () => {
  const detail = (highlightUtterance: number | null) => ({
    id: 1, title: 'Discovery call', happened_at: '2026-08-12T10:00:00Z', status: 'ready', source: 'upload', interviewer: 'David',
    company: { id: 1, name: 'Acme', domain: null, notes: null, conversation_count: 1, created_at: '2026-08-01T00:00:00Z' },
    contacts: [], meta: null, created_at: '2026-08-12T10:00:00Z',
    utterances: [1, 2, 3].map((i) => ({ id: i, idx: i, speaker_label: i === 1 ? 'David' : 'Maria', speaker_side: i === 1 ? 'us' : 'them', text: `Line number ${i}`, start_ms: null })),
    highlights: [{ id: 77, conversation_id: 1, utterance_id: highlightUtterance, tag_key: 'pain', quote: 'Line number 3', char_start: null, char_end: null,
      note: null, confidence: 0.9, origin: 'ai', status: 'accepted', created_at: '2026-08-12T12:00:00Z' }],
    analyses: [],
  });

  test('scrolls to and flashes the utterance that holds the quote', async () => {
    server.use(http.get('/api/conversations/1', () => HttpResponse.json(detail(3))));
    const scrolled: string[] = [];
    const original = Element.prototype.scrollIntoView;
    Element.prototype.scrollIntoView = function (this: Element) { scrolled.push(this.getAttribute('data-utterance-id') ?? ''); };
    try {
      renderWithProviders(<App />, { route: '/conversations/1?highlight=77' });
      await screen.findByText('Line number 3');
      await waitFor(() => expect(scrolled).toContain('3'));
      const line = document.querySelector('[data-utterance-id="3"]') as HTMLElement;
      await waitFor(() => expect(line.className).toMatch(/ring-2/));
    } finally {
      Element.prototype.scrollIntoView = original;
    }
  });

  test('a quote with no line (a manual one) or an unknown id just opens the call', async () => {
    for (const [route, utt] of [['/conversations/1?highlight=77', null], ['/conversations/1?highlight=99999', 3], ['/conversations/1?highlight=abc', 3]] as const) {
      server.use(http.get('/api/conversations/1', () => HttpResponse.json(detail(utt))));
      const view = renderWithProviders(<App />, { route });
      expect(await screen.findByText('Line number 3')).toBeInTheDocument();
      view.unmount();
    }
  });
});

describe('Hypothesis link: /hypotheses?hypothesis=:id', () => {
  const list = [1, 2].map((id) => ({
    id, statement: `Belief number ${id} about customers`, segment: null, status: 'open', created_by: 1, decided_at: null,
    created_at: '2026-08-01T00:00:00Z', verdict_hint: null,
    rollup: { supports: { confirmed: 1, suggested: 0 }, contradicts: { confirmed: 0, suggested: 0 }, companies_supporting: 1, companies_contradicting: 0,
      last_evidence_at: null, freshness: 'fresh', newest_evidence_at: null, grounding: 'candidate', pending_count: 0, grounding_reason: 'One quote.' },
  }));
  const handlers = () => server.use(
    http.get('/api/hypotheses', () => HttpResponse.json({ items: list, total: 2 })),
    http.get('/api/hypotheses/segments', () => HttpResponse.json({ items: [] })),
    http.get('/api/hypotheses/band-rules', () => HttpResponse.json({ items: [] })),
    http.get('/api/hypotheses/:id', ({ params }) => HttpResponse.json({ ...list[Number(params.id) - 1], evidence: { supports: [], contradicts: [] },
      supports: {}, contradicts: {}, links: [], questions: [] })),
  );

  test('opens that belief’s detail panel', async () => {
    handlers();
    renderWithProviders(<App />, { route: '/hypotheses?hypothesis=2' });
    const panel = await screen.findByTestId('hypothesis-detail');
    expect(panel).toHaveAccessibleName(/Belief number 2 about customers/);
  });

  test('an unknown or malformed id leaves the board as it is', async () => {
    handlers();
    for (const id of ['999', 'abc', '']) {
      const view = renderWithProviders(<App />, { route: `/hypotheses?hypothesis=${id}` });
      await screen.findByText(/Belief number 1 about customers/);
      expect(screen.queryByTestId('hypothesis-detail')).not.toBeInTheDocument();
      view.unmount();
    }
  });
});

describe('Decision link: /decisions?decision=:id', () => {
  test('opens that decision', async () => {
    renderWithProviders(<App />, { route: '/decisions?decision=2' });
    const detail = await screen.findByText('Enterprise users report manual export pain weekly.');
    expect(detail).toBeInTheDocument();
  });

  test('requests the decision it was given', async () => {
    const asked: string[] = [];
    server.use(http.get('/api/decisions/:id', ({ params }) => {
      asked.push(String(params.id));
      return HttpResponse.json({ id: Number(params.id), title: 'T', rationale_md: 'R', status: 'decided', integrity: 'ok', integrity_reasons: null,
        hypothesis_id: null, decided_at: null, decided_by: null, superseded_by: null, evidence: [], created_at: '2026-08-01T00:00:00Z' });
    }));
    renderWithProviders(<App />, { route: '/decisions?decision=2' });
    await waitFor(() => expect(asked).toContain('2'));
  });

  test('does not interfere with the existing prefill parameters, and ignores nonsense', async () => {
    renderWithProviders(<App />, { route: '/decisions?decision=zzz' });
    expect(await screen.findByText('Build auto-reports')).toBeInTheDocument();
    expect(screen.queryByText('Enterprise users report manual export pain weekly.')).not.toBeInTheDocument();
  });
});

describe('Summary link: /summaries?summary=:id', () => {
  test('selects that summary instead of the first one', async () => {
    server.use(http.get('/api/syntheses', () => HttpResponse.json({ items: [synthesis(1, 'First theme'), synthesis(2, 'Second theme')], total: 2 })));
    renderWithProviders(<App />, { route: '/summaries?summary=2' });
    const cards = await screen.findAllByTestId('summary-card');
    expect(cards).toHaveLength(2);
    await waitFor(() => expect(screen.getAllByText('Second theme').length).toBeGreaterThan(0));
    const selected = cards.find((c) => c.getAttribute('data-synthesis-id') === '2') as HTMLElement;
    expect(selected.className).not.toBe(cards.find((c) => c.getAttribute('data-synthesis-id') === '1')!.className);
    expect(within(document.body).queryByText('First theme', { selector: 'h2, h3' })).not.toBeInTheDocument();
  });

  test('an unknown id falls back to the first summary', async () => {
    server.use(http.get('/api/syntheses', () => HttpResponse.json({ items: [synthesis(1, 'First theme'), synthesis(2, 'Second theme')], total: 2 })));
    renderWithProviders(<App />, { route: '/summaries?summary=404' });
    await screen.findAllByTestId('summary-card');
    await waitFor(() => expect(screen.getAllByText('First theme').length).toBeGreaterThan(0));
  });
});
