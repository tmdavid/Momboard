/** v0.5 U8: weekly line charts with points, a placeholder until two weeks of calls, honest titles. */
import { describe, expect, test } from 'vitest';
import { screen, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { server } from '../test/mocks/server';
import { renderWithProviders } from '../test/render';
import { InsightsPage } from '../pages/InsightsPage';

function stats(over: Record<string, unknown> = {}) {
  return {
    total_conversations: 1234,
    tag_counts_by_month: { '2026-11': { pain: 1500, workaround: 20 } },
    critique_trend: [
      { date: '2026-11-02', score: 6 }, { date: '2026-11-09', score: 7.5 }, { date: '2026-11-16', score: 8 },
    ],
    compliment_ratio_trend: [
      { date: '2026-11-02', ratio: 0.3 }, { date: '2026-11-09', ratio: 0.2 }, { date: '2026-11-16', ratio: 0.1 },
    ],
    avg_critique_score: 7.2,
    avg_compliment_ratio: 0.2,
    open_followups: [],
    stale_hypotheses: 0,
    ...over,
  };
}
const serve = (s: ReturnType<typeof stats>) => server.use(http.get('/api/stats', () => HttpResponse.json(s)));

describe('Insights trends', () => {
  test('the volume card is titled for what it is: a total by tag', async () => {
    serve(stats());
    renderWithProviders(<InsightsPage />);
    expect(await screen.findByText('Signal volume by tag')).toBeInTheDocument();
    expect(screen.queryByText('Signal volume over time')).not.toBeInTheDocument();
  });

  test('trends are lines with a point for every week', async () => {
    serve(stats());
    renderWithProviders(<InsightsPage />);
    const quality = (await screen.findByText('Interview quality trend')).closest('section') as HTMLElement;
    const chart = within(quality).getByRole('img', { name: /interview quality by week/i });
    expect(chart.querySelectorAll('polyline')).toHaveLength(1);
    expect(chart.querySelectorAll('circle')).toHaveLength(3);
    expect(chart.querySelectorAll('rect')).toHaveLength(0);          // lines, not bars
    expect(within(quality).getByText('2 Nov')).toBeInTheDocument();  // week labels are readable dates
    expect(within(quality).getByText('16 Nov')).toBeInTheDocument();
  });

  test('with one week of data both trends show the placeholder instead of a lone bar', async () => {
    serve(stats({
      critique_trend: [{ date: '2026-11-09', score: 7 }],
      compliment_ratio_trend: [{ date: '2026-11-09', ratio: 0.2 }],
    }));
    renderWithProviders(<InsightsPage />);
    const quality = (await screen.findByText('Interview quality trend')).closest('section') as HTMLElement;
    const ratio = screen.getByText('Compliment ratio trend').closest('section') as HTMLElement;
    for (const card of [quality, ratio]) {
      expect(within(card).getByText('Trends appear after two weeks of calls')).toBeInTheDocument();
      expect(card.querySelector('svg')).toBeNull();
    }
  });

  test('two weeks is enough to draw the line', async () => {
    serve(stats({
      critique_trend: [{ date: '2026-11-02', score: 6 }, { date: '2026-11-09', score: 7 }],
    }));
    renderWithProviders(<InsightsPage />);
    const quality = (await screen.findByText('Interview quality trend')).closest('section') as HTMLElement;
    expect(within(quality).queryByText(/trends appear after two weeks/i)).not.toBeInTheDocument();
    expect(quality.querySelectorAll('circle')).toHaveLength(2);
  });

  test('the headline cards use the overall averages and thousands separators', async () => {
    serve(stats());
    renderWithProviders(<InsightsPage />);
    expect(await screen.findByText('1,234')).toBeInTheDocument();       // conversations
    expect(screen.getAllByText('1,500')).toHaveLength(2);               // the pains card and the volume row
    expect(screen.getByText('7.2/10')).toBeInTheDocument();             // overall, not the latest week (8)
    expect(screen.getByText('20%')).toBeInTheDocument();                // overall, not the latest week (10%)
  });

  test('no data at all keeps the empty message', async () => {
    serve(stats({ critique_trend: [], compliment_ratio_trend: [], tag_counts_by_month: {}, avg_critique_score: null, avg_compliment_ratio: null, total_conversations: 0 }));
    renderWithProviders(<InsightsPage />);
    expect(await screen.findByText(/Not enough data yet to show charts/)).toBeInTheDocument();
  });

  test('an old-style datetime date still draws without crashing', async () => {
    serve(stats({
      critique_trend: [{ date: '2026-11-02T00:00:00Z', score: 6 }, { date: '2026-11-09T00:00:00Z', score: 7 }],
    }));
    renderWithProviders(<InsightsPage />);
    const quality = (await screen.findByText('Interview quality trend')).closest('section') as HTMLElement;
    expect(within(quality).getByText('2 Nov')).toBeInTheDocument();
  });
});

describe('Insights labels say what is counted', () => {
  test('pains and the volume card admit that suggested highlights above the floor are included', async () => {
    serve(stats());
    renderWithProviders(<InsightsPage />);
    // Once under the Pains captured card, once under the volume card.
    expect(await screen.findAllByText(/accepted and suggested, above the confidence floor/i)).toHaveLength(2);
    expect(screen.queryByText('Accepted pain highlights')).not.toBeInTheDocument();
  });
});
