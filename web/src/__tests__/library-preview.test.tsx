/** v0.5 U5: clicking a Library row opens a preview panel instead of navigating away. */
import { describe, expect, test } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { Route, Routes, useLocation } from 'react-router-dom';
import { server } from '../test/mocks/server';
import { renderWithProviders } from '../test/render';
import { LibraryPage } from '../pages/LibraryPage';

const convo = (id: number) => ({
  id, title: `Call ${id}`, happened_at: '2026-11-02T09:00:00Z', status: 'ready', interviewer: 'Rep',
  company: { id: 40 + id, name: `Company ${id}` }, contacts: [], meta: null, created_at: '2026-11-02T09:00:00Z',
  tag_counts: { pain: 2 }, critique_score: 7,
});

const preview = (id: number, over: Record<string, unknown> = {}) => ({
  id, title: `Call ${id}`, happened_at: '2026-11-02T09:00:00Z', status: 'ready', company_id: 40 + id, company_name: `Company ${id}`,
  summary: 'They want a pilot before an annual contract.',
  top_pains: [{ pain: 'Manual review eats a day a week', severity: 'high' }, { pain: 'No proof of coverage', severity: 'medium' }],
  score: 7, followups: ['Send the pilot proposal'], suggestions_to_review: 12, ...over,
});

function Where() {
  const loc = useLocation();
  return <div data-testid="where">{loc.pathname}</div>;
}

function setup(over: Record<string, unknown> = {}) {
  server.use(
    http.get('/api/conversations', () => HttpResponse.json({ items: [convo(1), convo(2)], total: 2, limit: 50, offset: 0 })),
    http.get('/api/conversations/:id/preview', ({ params }) => HttpResponse.json(preview(Number(params.id), over))),
  );
  return renderWithProviders(
    <>
      <Routes>
        <Route path="/" element={<LibraryPage />} />
        <Route path="/conversations/:id" element={<div>conversation page</div>} />
        <Route path="/companies/:id" element={<div>company page</div>} />
      </Routes>
      <Where />
    </>,
    { route: '/' },
  );
}

describe('Library preview panel', () => {
  test('clicking a row opens the panel and stays on the Library', async () => {
    const user = userEvent.setup();
    setup();
    await user.click(await screen.findByText('Call 1'));
    const panel = await screen.findByRole('complementary', { name: /conversation preview/i });
    expect(screen.getByTestId('where')).toHaveTextContent('/');
    expect(await within(panel).findByText(/They want a pilot before an annual contract/)).toBeInTheDocument();
    expect(within(panel).getByText('Manual review eats a day a week')).toBeInTheDocument();
    expect(within(panel).getByText('No proof of coverage')).toBeInTheDocument();
    expect(within(panel).getByText(/Send the pilot proposal/)).toBeInTheDocument();
    expect(within(panel).getByText('7')).toBeInTheDocument();
    expect(within(panel).getByText(/12 tag suggestions to review/i)).toBeInTheDocument();
  });

  test('"Open conversation" goes to the full page', async () => {
    const user = userEvent.setup();
    setup();
    await user.click(await screen.findByText('Call 1'));
    const panel = await screen.findByRole('complementary', { name: /conversation preview/i });
    await user.click(await within(panel).findByRole('link', { name: /open conversation/i }));
    expect(await screen.findByText('conversation page')).toBeInTheDocument();
    expect(screen.getByTestId('where')).toHaveTextContent('/conversations/1');
  });

  test('clicking the company name still opens the full company page, not the panel', async () => {
    const user = userEvent.setup();
    setup();
    await screen.findByText('Call 1');
    await user.click(screen.getByRole('link', { name: 'Company 1' }));
    expect(await screen.findByText('company page')).toBeInTheDocument();
    expect(screen.queryByRole('complementary', { name: /conversation preview/i })).not.toBeInTheDocument();
  });

  test('Escape closes the panel and returns focus to the row', async () => {
    const user = userEvent.setup();
    setup();
    const title = await screen.findByText('Call 1');
    const row = title.closest('tr') as HTMLElement;
    await user.click(title);
    await screen.findByRole('complementary', { name: /conversation preview/i });
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('complementary', { name: /conversation preview/i })).not.toBeInTheDocument();
    expect(row).toHaveFocus();
  });

  test('the Close button closes it too', async () => {
    const user = userEvent.setup();
    setup();
    await user.click(await screen.findByText('Call 1'));
    const panel = await screen.findByRole('complementary', { name: /conversation preview/i });
    await user.click(within(panel).getByRole('button', { name: /close preview/i }));
    expect(screen.queryByRole('complementary', { name: /conversation preview/i })).not.toBeInTheDocument();
  });

  test('clicking another row swaps the panel to that call', async () => {
    const user = userEvent.setup();
    setup();
    await user.click(await screen.findByText('Call 1'));
    await screen.findByRole('complementary', { name: /conversation preview/i });
    await user.click(screen.getByText('Call 2'));
    expect(await screen.findByRole('heading', { name: 'Call 2' })).toBeInTheDocument();
    expect(screen.getAllByRole('complementary', { name: /conversation preview/i })).toHaveLength(1);
  });

  test('rows are keyboard-activatable (Enter opens the panel)', async () => {
    const user = userEvent.setup();
    setup();
    const row = (await screen.findByText('Call 1')).closest('tr') as HTMLElement;
    expect(row).toHaveAttribute('tabindex', '0');
    row.focus();
    await user.keyboard('{Enter}');
    expect(await screen.findByRole('complementary', { name: /conversation preview/i })).toBeInTheDocument();
  });

  test('a call with no analysis says so instead of showing blanks', async () => {
    const user = userEvent.setup();
    setup({ summary: null, top_pains: [], score: null, followups: [], suggestions_to_review: 0 });
    await user.click(await screen.findByText('Call 1'));
    const panel = await screen.findByRole('complementary', { name: /conversation preview/i });
    expect(await within(panel).findByText(/no summary yet/i)).toBeInTheDocument();
    expect(within(panel).queryByText(/to review/i)).not.toBeInTheDocument();
  });

  test('a failed preview shows an error and still offers Open conversation', async () => {
    const user = userEvent.setup();
    setup();
    server.use(http.get('/api/conversations/:id/preview', () => new HttpResponse(null, { status: 500 })));
    await user.click(await screen.findByText('Call 1'));
    const panel = await screen.findByRole('complementary', { name: /conversation preview/i });
    expect(await within(panel).findByRole('alert')).toBeInTheDocument();
    expect(within(panel).getByRole('link', { name: /open conversation/i })).toBeInTheDocument();
  });
});
