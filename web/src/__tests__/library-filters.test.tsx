/**
 * RED-phase tests: T15 — Multi-tag/date filters and real 300ms debounce.
 *
 * Acceptance criteria:
 * - Multiple tags can be selected simultaneously (repeated tag query params).
 * - Date range filters (date_from, date_to) narrow the results.
 * - Free-text search debounces at 300ms exactly:
 *   - typing characters within 300ms sends only one request.
 *   - after 300ms of no typing, request fires with full q= value.
 * - name_colon format: contacts displayed as "Name: Role" (with colon separator).
 */
import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest';
import { screen, waitFor, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { server } from '../test/mocks/server';
import { renderWithProviders } from '../test/render';
import { App } from '../App';

describe('T15 — Multi-tag filter', () => {
  test('selecting two tags sends repeated tag= params and narrows results', async () => {
    const requestUrls: string[] = [];

    server.use(
      http.get('/api/conversations', ({ request }) => {
        requestUrls.push(request.url);
        const url = new URL(request.url);
        const tags = url.searchParams.getAll('tag');
        // Only return items that have ALL selected tags
        if (tags.includes('pain') && tags.includes('money')) {
          return HttpResponse.json({
            items: [{
              id: 1, title: 'Multi-tag match',
              happened_at: '2026-08-12T10:00:00Z', status: 'ready', interviewer: 'David',
              company: { id: 1, name: 'Acme', domain: null, notes: null, created_at: '2026-08-01T00:00:00Z' },
              contacts: [{ id: 1, name: 'Jane Doe', role: 'Brand Manager', email: null, company_id: 1, created_at: '2026-08-01T00:00:00Z' }],
              meta: null, created_at: '2026-08-12T10:00:00Z',
              tag_counts: { pain: 3, money: 2 }, critique_score: 7,
            }],
            total: 1, limit: 50, offset: 0,
          });
        }
        return HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 });
      }),
    );

    renderWithProviders(<App />);
    const user = userEvent.setup();

    await waitFor(() => {
      expect(screen.getByPlaceholderText(/search/i)).toBeInTheDocument();
    });

    // Click first tag: ⚡ pain
    const painBtn = screen.getByRole('button', { name: /⚡ pain/i });
    await user.click(painBtn);

    // Click second tag: 💰 money
    const moneyBtn = screen.getByRole('button', { name: /💰 money/i });
    await user.click(moneyBtn);

    await waitFor(() => {
      expect(screen.getByText('Multi-tag match')).toBeInTheDocument();
    });

    // Verify both tags were sent as separate query params
    const lastUrl = requestUrls[requestUrls.length - 1];
    const parsedUrl = new URL(lastUrl);
    const tagParams = parsedUrl.searchParams.getAll('tag');
    expect(tagParams).toContain('pain');
    expect(tagParams).toContain('money');
    expect(tagParams.length).toBe(2);
  });

  test('deselecting a tag removes it from the query without affecting the other', async () => {
    const requestUrls: string[] = [];

    server.use(
      http.get('/api/conversations', ({ request }) => {
        requestUrls.push(request.url);
        return HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 });
      }),
    );

    renderWithProviders(<App />);
    const user = userEvent.setup();

    await waitFor(() => {
      expect(screen.getByPlaceholderText(/search/i)).toBeInTheDocument();
    });

    // Select pain
    await user.click(screen.getByRole('button', { name: /⚡ pain/i }));
    // Select money
    await user.click(screen.getByRole('button', { name: /💰 money/i }));
    // Deselect pain
    await user.click(screen.getByRole('button', { name: /⚡ pain/i }));

    await waitFor(() => {
      const lastUrl = requestUrls[requestUrls.length - 1];
      const parsedUrl = new URL(lastUrl);
      const tagParams = parsedUrl.searchParams.getAll('tag');
      expect(tagParams).toEqual(['money']);
    });
  });
});

describe('T15 — Date range filter', () => {
  test('setting date_from and date_to sends both as query params', async () => {
    const requestUrls: string[] = [];

    server.use(
      http.get('/api/conversations', ({ request }) => {
        requestUrls.push(request.url);
        return HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 });
      }),
    );

    renderWithProviders(<App />);
    const user = userEvent.setup();

    await waitFor(() => {
      expect(screen.getByPlaceholderText(/search/i)).toBeInTheDocument();
    });

    // Look for date inputs (date_from, date_to)
    const dateFromInput = screen.getByLabelText(/from/i);
    const dateToInput = screen.getByLabelText(/to/i);

    await user.type(dateFromInput, '2026-08-01');
    await user.type(dateToInput, '2026-08-15');

    await waitFor(() => {
      const lastUrl = requestUrls[requestUrls.length - 1];
      const parsedUrl = new URL(lastUrl);
      expect(parsedUrl.searchParams.get('date_from')).toBe('2026-08-01');
      expect(parsedUrl.searchParams.get('date_to')).toBe('2026-08-15');
    });
  });
});

describe('T15 — Search debounce (300ms)', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  test('typing rapidly within 300ms sends only one request after the debounce', async () => {
    const requestUrls: string[] = [];

    server.use(
      http.get('/api/conversations', ({ request }) => {
        requestUrls.push(request.url);
        return HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 });
      }),
    );

    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderWithProviders(<App />);

    // Wait for initial load
    await waitFor(() => {
      expect(screen.getByPlaceholderText(/search/i)).toBeInTheDocument();
    });

    const searchInput = screen.getByPlaceholderText(/search/i);
    // Type "abc" rapidly
    await user.type(searchInput, 'a');
    await user.type(searchInput, 'b');
    await user.type(searchInput, 'c');

    // Before 300ms, no new request
    const midCount = requestUrls.filter(u => new URL(u).searchParams.has('q')).length;
    expect(midCount).toBe(0);

    // Advance past 300ms debounce
    await act(async () => {
      vi.advanceTimersByTime(350);
    });

    // Now exactly one request with q=abc
    await waitFor(() => {
      const qRequests = requestUrls.filter(u => new URL(u).searchParams.get('q') === 'abc');
      expect(qRequests.length).toBe(1);
    });
  });

  test('clearing the search field after debounce removes q= and re-fetches', async () => {
    const requestUrls: string[] = [];

    server.use(
      http.get('/api/conversations', ({ request }) => {
        requestUrls.push(request.url);
        return HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 });
      }),
    );

    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderWithProviders(<App />);

    await waitFor(() => {
      expect(screen.getByPlaceholderText(/search/i)).toBeInTheDocument();
    });

    const searchInput = screen.getByPlaceholderText(/search/i);
    await user.type(searchInput, 'test');

    await act(async () => {
      vi.advanceTimersByTime(350);
    });

    // Clear
    await user.clear(searchInput);

    await act(async () => {
      vi.advanceTimersByTime(350);
    });

    // Last request should not have q param
    await waitFor(() => {
      const lastUrl = requestUrls[requestUrls.length - 1];
      const parsedUrl = new URL(lastUrl);
      expect(parsedUrl.searchParams.has('q')).toBe(false);
    });
  });
});

describe('T15 — name_colon format', () => {
  test('contacts are displayed as "Name: Role" format in the library row', async () => {
    server.use(
      http.get('/api/conversations', () =>
        HttpResponse.json({
          items: [{
            id: 1, title: 'Test convo',
            happened_at: '2026-08-12T10:00:00Z', status: 'ready', interviewer: 'David',
            company: { id: 1, name: 'TestCo', domain: null, notes: null, created_at: '2026-08-01T00:00:00Z' },
            contacts: [
              { id: 1, name: 'Jane Doe', role: 'Brand Manager', email: null, company_id: 1, created_at: '2026-08-01T00:00:00Z' },
              { id: 2, name: 'John Smith', role: 'CTO', email: null, company_id: 1, created_at: '2026-08-01T00:00:00Z' },
            ],
            meta: null, created_at: '2026-08-12T10:00:00Z',
            tag_counts: { pain: 2 }, critique_score: 7,
          }],
          total: 1, limit: 50, offset: 0,
        }),
      ),
    );

    renderWithProviders(<App />);

    await waitFor(() => {
      expect(screen.getByText('Test convo')).toBeInTheDocument();
    });

    // Should show "Name: Role" (with colon, not "·")
    expect(screen.getByText(/Jane Doe: Brand Manager/)).toBeInTheDocument();
    expect(screen.getByText(/John Smith: CTO/)).toBeInTheDocument();
  });
});
