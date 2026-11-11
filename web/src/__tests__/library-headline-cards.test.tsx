/** v0.5 U12: headline number cards on the Library, each linking to the page behind the number. */
import { describe, expect, test } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { Route, Routes, useLocation } from 'react-router-dom';
import { server } from '../test/mocks/server';
import { renderWithProviders } from '../test/render';
import { LibraryPage } from '../pages/LibraryPage';
import { ExplorePage } from '../pages/ExplorePage';

const stats = (over: Record<string, unknown> = {}) => ({
  total_conversations: 1234,
  tag_counts_by_month: { '2026-10': { pain: 1000, workaround: 5 }, '2026-11': { pain: 500 } },
  critique_trend: [], compliment_ratio_trend: [],
  avg_critique_score: 6.5, avg_compliment_ratio: 0.18,
  open_followups: [], stale_hypotheses: 0, ...over,
});

function Where() {
  const l = useLocation();
  return <div data-testid="where">{l.pathname + l.search}</div>;
}

function setup(s: unknown = stats()) {
  server.use(
    http.get('/api/stats', () => HttpResponse.json(s as Record<string, unknown>)),
    http.get('/api/conversations', () => HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 })),
  );
  return renderWithProviders(
    <>
      <Routes>
        <Route path="/" element={<LibraryPage />} />
        <Route path="/insights" element={<div>insights page</div>} />
        <Route path="/explore" element={<ExplorePage />} />
      </Routes>
      <Where />
    </>,
    { route: '/' },
  );
}

describe('Library headline cards', () => {
  test('shows the four numbers, formatted', async () => {
    setup();
    const cards = await screen.findByRole('navigation', { name: /headline numbers/i });
    expect(within(cards).getByText('1,234')).toBeInTheDocument();
    expect(within(cards).getByText('6.5/10')).toBeInTheDocument();
    expect(within(cards).getByText('1,500')).toBeInTheDocument();
    expect(within(cards).getByText('18%')).toBeInTheDocument();
  });

  test('each card links to the page behind the number', async () => {
    setup();
    const cards = await screen.findByRole('navigation', { name: /headline numbers/i });
    expect(within(cards).getByRole('link', { name: /total conversations/i })).toHaveAttribute('href', '/');
    expect(within(cards).getByRole('link', { name: /average interview score/i })).toHaveAttribute('href', '/insights');
    expect(within(cards).getByRole('link', { name: /pains captured/i })).toHaveAttribute('href', '/explore?tag=pain');
    expect(within(cards).getByRole('link', { name: /compliment ratio/i })).toHaveAttribute('href', '/insights');
  });

  test('Pains captured opens Explore already filtered to pain only', async () => {
    const user = userEvent.setup();
    setup();
    const cards = await screen.findByRole('navigation', { name: /headline numbers/i });
    await user.click(within(cards).getByRole('link', { name: /pains captured/i }));
    expect(screen.getByTestId('where')).toHaveTextContent('/explore?tag=pain');
    const pain = await screen.findByRole('button', { name: /pain/i, pressed: true });
    expect(pain).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /workaround/i, pressed: true })).not.toBeInTheDocument();
  });

  test('missing numbers show a dash, never NaN or 0%', async () => {
    setup(stats({ total_conversations: 0, tag_counts_by_month: {}, avg_critique_score: null, avg_compliment_ratio: null }));
    const cards = await screen.findByRole('navigation', { name: /headline numbers/i });
    expect(within(cards).getAllByText('—')).toHaveLength(4);
    expect(cards).not.toHaveTextContent(/NaN|0%/);
  });

  test('a failing stats request does not break the Library', async () => {
    server.use(http.get('/api/stats', () => new HttpResponse(null, { status: 500 })),
      http.get('/api/conversations', () => HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 })));
    renderWithProviders(<LibraryPage />, { route: '/' });
    expect(await screen.findByText(/no conversations yet/i)).toBeInTheDocument();
    expect(screen.queryByRole('navigation', { name: /headline numbers/i })).not.toBeInTheDocument();
  });
});
