/** v0.5 U11: Library rows grouped under a header per day instead of a date on every row. */
import { describe, expect, test, vi, beforeEach, afterEach } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { server } from '../test/mocks/server';
import { renderWithProviders } from '../test/render';
import { LibraryPage } from '../pages/LibraryPage';

const convo = (id: number, happened_at: string | null) => ({
  id, title: `Call ${id}`, happened_at, status: 'ready', interviewer: 'Rep', company: { id: id + 100, name: `Co ${id}` },
  contacts: [], meta: null, created_at: '2026-11-10T09:00:00Z', tag_counts: { pain: 1 }, critique_score: 6,
});

function setup(items: ReturnType<typeof convo>[], extra: { total?: number; limit?: number; offset?: number; route?: string } = {}) {
  server.use(http.get('/api/conversations', () => HttpResponse.json({
    items, total: extra.total ?? items.length, limit: extra.limit ?? 50, offset: extra.offset ?? 0,
  })));
  renderWithProviders(<LibraryPage />, { route: extra.route ?? '/' });
}

beforeEach(() => { vi.useFakeTimers({ toFake: ['Date'] }); vi.setSystemTime(new Date(2026, 10, 10, 15, 0)); });
afterEach(() => { vi.useRealTimers(); });

describe('Library day groups', () => {
  test('rows sit under a header per day with the number of calls', async () => {
    setup([convo(1, '2026-11-10T09:00:00'), convo(2, '2026-11-10T11:00:00'), convo(3, '2026-11-09T10:00:00')]);
    expect(await screen.findByRole('rowheader', { name: /Today · Tue 10 Nov · 2 calls/ })).toBeInTheDocument();
    expect(screen.getByRole('rowheader', { name: /Yesterday · Mon 9 Nov · 1 call$/ })).toBeInTheDocument();
  });

  test('there is no Date column and rows do not repeat the date', async () => {
    setup([convo(1, '2026-11-10T09:00:00')]);
    await screen.findByText('Call 1');
    expect(screen.queryByRole('columnheader', { name: /^date$/i })).not.toBeInTheDocument();
    const row = screen.getByText('Call 1').closest('tr') as HTMLElement;
    expect(within(row).queryByText(/10 Nov/)).not.toBeInTheDocument();
  });

  test('calls with no date go under "No date"', async () => {
    setup([convo(1, null)]);
    expect(await screen.findByRole('rowheader', { name: /No date · 1 call/ })).toBeInTheDocument();
  });

  test('sorted by score the list is not grouped and each row keeps its date', async () => {
    setup([convo(1, '2026-11-10T09:00:00'), convo(2, '2026-11-09T09:00:00')], { route: '/?sort=score_desc' });
    await screen.findByText('Call 1');
    expect(screen.queryByRole('rowheader')).not.toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: /^date$/i })).toBeInTheDocument();
    const row = screen.getByText('Call 1').closest('tr') as HTMLElement;
    expect(within(row).getByText('10 Nov 2026')).toBeInTheDocument();
  });

  test('a day cut by the page edge says how many are shown, not a false total', async () => {
    // 3 of the 10 calls are on this page, page 1 of several: the last day may continue on page 2.
    setup([convo(1, '2026-11-10T09:00:00'), convo(2, '2026-11-09T09:00:00'), convo(3, '2026-11-09T08:00:00')], { total: 10, limit: 3 });
    expect(await screen.findByRole('rowheader', { name: /Today · Tue 10 Nov · 1 call$/ })).toBeInTheDocument();
    expect(screen.getByRole('rowheader', { name: /Yesterday · Mon 9 Nov · 2 shown/ })).toBeInTheDocument();
  });

  test('a day that starts the second page is also marked as continuing', async () => {
    setup([convo(4, '2026-11-09T07:00:00'), convo(5, '2026-11-08T09:00:00')], { total: 5, limit: 3, offset: 3, route: '/?offset=3' });
    expect(await screen.findByRole('rowheader', { name: /Yesterday · Mon 9 Nov · 1 shown/ })).toBeInTheDocument();
    expect(screen.getByRole('rowheader', { name: /Sun 8 Nov · 1 call$/ })).toBeInTheDocument();     // last page: complete
  });

  test('clicking a row under a header still opens the preview', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    setup([convo(1, '2026-11-10T09:00:00')]);
    await user.click(await screen.findByText('Call 1'));
    expect(await screen.findByRole('complementary', { name: /conversation preview/i })).toBeInTheDocument();
  });
});
