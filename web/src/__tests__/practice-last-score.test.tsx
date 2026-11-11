/** v0.5 U10: "Last score" shows the latest finished session, not just one scored in this visit. */
import { describe, expect, test } from 'vitest';
import { screen, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { server } from '../test/mocks/server';
import { renderWithProviders } from '../test/render';
import { SimulatorPage } from '../pages/SimulatorPage';

const session = (id: number, score: number | null, created = '2026-11-10T09:00:00Z') => ({
  id, title: `Practice ${id}`, status: score == null ? 'processing' : 'ready', created_at: created, score, has_analysis: score != null,
});

function setup(items: ReturnType<typeof session>[], result?: unknown) {
  server.use(
    http.get('/api/simulator/sessions', () => HttpResponse.json({ items, total: items.length })),
    http.get('/api/simulator/sessions/:id/result', () =>
      result ? HttpResponse.json(result) : new HttpResponse(null, { status: 500 })),
  );
  renderWithProviders(<SimulatorPage />, { route: '/practice' });
}
const lastScore = () => screen.findByRole('region', { name: /last score/i });

describe('Practice: last score', () => {
  test('after a reload it shows the latest scored session, matching the past-sessions list', async () => {
    setup([session(3, null, '2026-11-12T09:00:00Z'), session(2, 7, '2026-11-10T09:00:00Z'), session(1, 4, '2026-11-01T09:00:00Z')], {
      analysis: { result: { mom_test_critique: { score: 7, good_questions: ['Walk me through last week'], violations: [{ utterance_idx: 2, type: 'Pitching', better: 'Ask about their current process' }] } } },
    });
    const panel = await lastScore();
    expect(await within(panel).findByText('7/10')).toBeInTheDocument();
    expect(within(panel).queryByText(/finish a session/i)).not.toBeInTheDocument();
    expect(within(panel).getByText(/10 Nov 2026/)).toBeInTheDocument();
    expect(await within(panel).findByText('Walk me through last week')).toBeInTheDocument();
    expect(within(panel).getByText(/Ask about their current process/)).toBeInTheDocument();
  });

  test('a session still being scored is skipped in favour of the latest finished one', async () => {
    setup([session(9, null), session(2, 6, '2026-11-02T09:00:00Z')], { analysis: { result: { mom_test_critique: { score: 6, good_questions: [], violations: [] } } } });
    const panel = await lastScore();
    expect(await within(panel).findByText('6/10')).toBeInTheDocument();
  });

  test('if the critique details fail to load, the score from the list still shows', async () => {
    setup([session(2, 7)]);                        // /result answers 500
    const panel = await lastScore();
    expect(await within(panel).findByText('7/10')).toBeInTheDocument();
  });

  test('with no finished session it keeps the prompt to finish one', async () => {
    setup([session(5, null)]);
    const panel = await lastScore();
    expect(await within(panel).findByText(/finish a session/i)).toBeInTheDocument();
  });

  test('with no sessions at all it keeps the prompt', async () => {
    setup([]);
    const panel = await lastScore();
    expect(await within(panel).findByText(/finish a session/i)).toBeInTheDocument();
  });
});
