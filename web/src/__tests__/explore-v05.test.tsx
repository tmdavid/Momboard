/** v0.5 D4/D7 in Explore: strongest first, a floor, a per-call cap, and an honest "not retagged" note. */
import { describe, expect, test } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { Route, Routes } from 'react-router-dom';
import { server } from '../test/mocks/server';
import { renderWithProviders } from '../test/render';
import { ExplorePage } from '../pages/ExplorePage';

const render = () =>
  renderWithProviders(<Routes><Route path="/explore" element={<ExplorePage />} /></Routes>, { route: '/explore' });

const item = (id: number, over: Record<string, unknown> = {}) => ({
  id, conversation_id: id, utterance_id: id, tag_key: 'pain', quote: `Quote number ${id}`, confidence: 0.9,
  status: 'suggested', origin: 'ai', conversation_title: `Call ${id}`, conversation_happened_at: '2026-11-02T09:00:00Z',
  company_name: `Company ${id}`, contact_names: ['Contact A'], ...over,
});

function capture() {
  const seen: URLSearchParams[] = [];
  server.use(
    http.get('/api/highlights', ({ request }) => {
      seen.push(new URL(request.url).searchParams);
      return HttpResponse.json({ items: [item(1), item(2)], total: 2, limit: 200, offset: 0 });
    }),
  );
  return seen;
}

describe('Explore default view', () => {
  test('asks for the strongest first, above each tag floor, at most 3 per call per tag', async () => {
    const seen = capture();
    render();
    await screen.findByText(/Quote number 1/);
    const p = seen.at(-1)!;
    expect(p.get('floor')).toBe('true');
    expect(p.get('sort')).toBe('confidence');
    expect(p.get('per_call_cap')).toBe('3');
  });

  test('"Show low-confidence" lifts the floor and the cap so nothing is hidden for good', async () => {
    const seen = capture();
    const user = userEvent.setup();
    render();
    await screen.findByText(/Quote number 1/);
    await user.click(screen.getByRole('checkbox', { name: /show low-confidence/i }));
    await waitFor(() => expect(seen.at(-1)!.get('floor')).toBeNull());
    expect(seen.at(-1)!.get('per_call_cap')).toBeNull();
    expect(seen.at(-1)!.get('sort')).toBe('confidence');
  });

  test('explains what the default view hides', async () => {
    capture();
    render();
    await screen.findByText(/Quote number 1/);
    expect(screen.getByText(/strongest first/i)).toBeInTheDocument();
  });
});

describe('Explore not-yet-retagged notice', () => {
  const stale = (n: number) =>
    http.get('/api/taxonomy/stale', () =>
      HttpResponse.json({ items: [{ key: 'pain', name: 'Pain', added_in_version: 2, total_calls: 1000, stale_calls: n }] }));

  test('appears when a filtered tag has not reached every call', async () => {
    capture();
    server.use(stale(312));
    render();
    expect(await screen.findByText(/Pain was added after 312 calls were tagged\. Retag them to include them\./)).toBeInTheDocument();
  });

  test('is absent when every call has the tag', async () => {
    capture();
    server.use(stale(0));
    render();
    await screen.findByText(/Quote number 1/);
    expect(screen.queryByTestId('retag-notice')).not.toBeInTheDocument();
  });
});

test('the empty message still helps when nothing is above the floor', async () => {
  server.use(http.get('/api/highlights', () => HttpResponse.json({ items: [], total: 0, limit: 200, offset: 0 })));
  render();
  const msg = await screen.findByText(/no highlights/i);
  expect(within(msg.closest('div')!).getByText(/low-confidence/i)).toBeInTheDocument();
});
