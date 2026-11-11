/** v0.5 Library fixes: U3 empty-result message, U4 strong pains, U7 compliments out of the top signals. */
import { describe, expect, test } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { server } from '../test/mocks/server';
import { renderWithProviders } from '../test/render';
import { App } from '../App';

const convo = (id: number, tag_counts: Record<string, number>) => ({
  id, title: `Call ${id}`, happened_at: '2026-11-02T09:00:00Z', status: 'ready', interviewer: 'Rep',
  company: { id: 1, name: `Company ${id}` }, contacts: [], meta: null, created_at: '2026-11-02T09:00:00Z',
  tag_counts, critique_score: 7,
});

const empty = () => HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 });

describe('U3: empty-result message', () => {
  test('an empty library with no filters still says "No conversations yet"', async () => {
    server.use(http.get('/api/conversations', empty));
    renderWithProviders(<App />, { route: '/' });
    expect(await screen.findByText(/no conversations yet/i)).toBeInTheDocument();
    expect(screen.queryByText(/match these filters/i)).not.toBeInTheDocument();
    expect(within(screen.getByTestId('empty-library')).getByRole('button', { name: /new conversation/i })).toBeInTheDocument();
  });

  test('filters that match nothing say so, list the filters, and offer Clear filters next to New conversation', async () => {
    server.use(http.get('/api/conversations', empty));
    renderWithProviders(<App />, { route: '/?q=pricing&tag=pain&company_id=3&date_from=2026-11-01' });
    const box = await screen.findByTestId('empty-filtered');
    expect(within(box).getByText(/no conversations match these filters/i)).toBeInTheDocument();
    expect(screen.queryByText(/no conversations yet/i)).not.toBeInTheDocument();
    const active = within(box).getByRole('list', { name: /active filters/i });
    expect(within(active).getByText(/pricing/)).toBeInTheDocument();
    expect(within(active).getByText(/pain/i)).toBeInTheDocument();
    expect(within(active).getByText(/1 Nov 2026/)).toBeInTheDocument();
    expect(within(box).getByRole('button', { name: /clear filters/i })).toBeInTheDocument();
    expect(within(box).getByRole('button', { name: /new conversation/i })).toBeInTheDocument();
  });

  test('Clear filters removes them and reloads the list', async () => {
    let lastQuery = '';
    server.use(
      http.get('/api/conversations', ({ request }) => {
        lastQuery = new URL(request.url).search;
        return new URL(request.url).searchParams.get('tag')
          ? empty()
          : HttpResponse.json({ items: [convo(1, { pain: 2 })], total: 1, limit: 50, offset: 0 });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<App />, { route: '/?tag=pain' });
    await user.click(await screen.findByRole('button', { name: /clear filters/i }));
    expect(await screen.findByText('Call 1')).toBeInTheDocument();
    expect(lastQuery).not.toContain('tag=');
  });

  test('says when a filtered tag has not reached every call yet', async () => {
    server.use(
      http.get('/api/conversations', empty),
      http.get('/api/taxonomy/stale', ({ request }) => {
        expect(new URL(request.url).searchParams.getAll('tag')).toEqual(['impersonation']);
        return HttpResponse.json({ items: [{ key: 'impersonation', name: 'Impersonation', added_in_version: 3, total_calls: 1000, stale_calls: 688 }] });
      }),
    );
    renderWithProviders(<App />, { route: '/?tag=impersonation' });
    const box = await screen.findByTestId('empty-filtered');
    expect(await within(box).findByText(/Impersonation was added after 688 calls were tagged\. Retag them to include them\./)).toBeInTheDocument();
  });

  test('stays quiet about retagging when no filtered tag is missing from any call', async () => {
    server.use(
      http.get('/api/conversations', empty),
      http.get('/api/taxonomy/stale', () => HttpResponse.json({ items: [{ key: 'pain', name: 'Pain', added_in_version: 0, total_calls: 1000, stale_calls: 0 }] })),
    );
    renderWithProviders(<App />, { route: '/?tag=pain' });
    const box = await screen.findByTestId('empty-filtered');
    await waitFor(() => expect(within(box).queryByText(/retag them/i)).not.toBeInTheDocument());
  });
});

describe('U4: Strong pains', () => {
  test('means a call with a pain AND a workaround, and says so in a tooltip', async () => {
    const queries: string[] = [];
    server.use(
      http.get('/api/conversations', ({ request }) => {
        queries.push(new URL(request.url).searchParams.getAll('tag').join(','));
        return HttpResponse.json({ items: [convo(1, { pain: 2, workaround: 1 })], total: 1, limit: 50, offset: 0 });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<App />, { route: '/' });
    await screen.findByText('Call 1');
    const tab = screen.getByRole('tab', { name: /strong pains/i });
    expect(tab).toHaveAttribute('title', expect.stringMatching(/pain and a workaround/i));
    await user.click(tab);
    await waitFor(() => expect(queries.at(-1)).toBe('pain,workaround'));
    expect(screen.getByRole('tab', { name: /strong pains/i })).toHaveAttribute('aria-selected', 'true');
  });

  test('a single Pain filter is no longer the Strong pains view', async () => {
    renderWithProviders(<App />, { route: '/?tag=pain' });
    await screen.findByRole('tab', { name: /strong pains/i });
    expect(screen.getByRole('tab', { name: /strong pains/i })).toHaveAttribute('aria-selected', 'false');
  });
});

describe('U7: compliments are never a top signal', () => {
  test('the top-3 text skips Compliment even when it is the biggest count', async () => {
    server.use(http.get('/api/conversations', () => HttpResponse.json({
      items: [convo(1, { compliment: 9, pain: 3, workaround: 2, money: 1, obstacle: 1 })], total: 1, limit: 50, offset: 0 })));
    renderWithProviders(<App />, { route: '/' });
    const row = (await screen.findByText('Call 1')).closest('tr') as HTMLElement;
    const text = row.querySelector('.trunc')!.textContent ?? '';
    expect(text).not.toMatch(/compliment/i);
    expect(text).toMatch(/Pain 3/);
    expect(text).toMatch(/Workaround 2/);
    expect(text).toMatch(/\+/);   // the rest (incl. compliments) is summarised, not named
  });

  test('in the bar compliment is drawn last, in light grey', async () => {
    server.use(http.get('/api/conversations', () => HttpResponse.json({
      items: [convo(1, { compliment: 9, pain: 3, workaround: 2 })], total: 1, limit: 50, offset: 0 })));
    renderWithProviders(<App />, { route: '/' });
    const row = (await screen.findByText('Call 1')).closest('tr') as HTMLElement;
    const segments = Array.from(row.querySelectorAll('[role="img"] > span')) as HTMLElement[];
    expect(segments).toHaveLength(3);
    expect(segments.at(-1)!.getAttribute('data-tag')).toBe('compliment');
    expect(segments.at(-1)!.style.background).toMatch(/#d1d5db|rgb\(209, 213, 219\)/i);
    expect(segments[0].getAttribute('data-tag')).toBe('pain');
  });

  test('a call that is only compliments still shows something sensible', async () => {
    server.use(http.get('/api/conversations', () => HttpResponse.json({
      items: [convo(1, { compliment: 4 })], total: 1, limit: 50, offset: 0 })));
    renderWithProviders(<App />, { route: '/' });
    const row = (await screen.findByText('Call 1')).closest('tr') as HTMLElement;
    expect(row.querySelector('.trunc')!.textContent).toMatch(/\+4 more|only compliments/i);
  });
});
