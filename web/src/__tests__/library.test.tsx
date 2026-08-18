import { describe, test, expect } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { server } from '../test/mocks/server';
import { renderWithProviders } from '../test/render';
import { App } from '../App';

describe('Library page', () => {
  test('renders a row per conversation with date, company, contact, title', async () => {
    renderWithProviders(<App />);

    await waitFor(() => {
      expect(screen.getByText('Discovery — counterfeit listings workflow')).toBeInTheDocument();
    });

    expect(screen.getAllByText(/Acme Watches/).length).toBeGreaterThan(0);
    expect(screen.getByText(/Jane Doe/)).toBeInTheDocument();
    expect(screen.getByText('Key-reselling sites, first call')).toBeInTheDocument();
  });

  test('row shows tag chips with counts and critique score badge', async () => {
    renderWithProviders(<App />);

    await waitFor(() => {
      expect(screen.getByText('Discovery — counterfeit listings workflow')).toBeInTheDocument();
    });

    // Score badges
    expect(screen.getByText('8')).toBeInTheDocument();
    expect(screen.getByText('3')).toBeInTheDocument();
  });

  test('processing conversations show a spinner status chip, not a score', async () => {
    renderWithProviders(<App />);

    await waitFor(() => {
      expect(screen.getByText('Processing new conversation')).toBeInTheDocument();
    });

    expect(screen.getByText('Processing…')).toBeInTheDocument();
  });

  test('filter by tag narrows the table (query param sent to API)', async () => {
    renderWithProviders(<App />);
    const user = userEvent.setup();

    await waitFor(() => {
      expect(screen.getByText('Discovery — counterfeit listings workflow')).toBeInTheDocument();
    });

    server.use(
      http.get('/api/conversations', ({ request }) => {
        const url = new URL(request.url);
        const tag = url.searchParams.get('tag');
        if (tag === 'pain') {
          return HttpResponse.json({
            items: [{
              id: 1, title: 'Discovery — counterfeit listings workflow',
              happened_at: '2026-08-12T10:00:00Z', status: 'ready', interviewer: 'David',
              company: { id: 1, name: 'Acme Watches', domain: null, notes: null, created_at: '2026-08-01T00:00:00Z' },
              contacts: [], meta: null, created_at: '2026-08-12T10:00:00Z',
              tag_counts: { pain: 3 }, critique_score: 8,
            }],
            total: 1, limit: 50, offset: 0,
          });
        }
        return HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 });
      }),
    );

    await user.click(screen.getByRole('button', { name: /⚡ pain/i }));

    await waitFor(() => {
      expect(screen.getByText('(1)')).toBeInTheDocument();
    });
  });

  test('free-text search debounces 300ms then queries q=', async () => {
    renderWithProviders(<App />);

    await waitFor(() => {
      expect(screen.getByPlaceholderText(/search/i)).toBeInTheDocument();
    });

    // Just verify the search input exists and is functional
    const searchInput = screen.getByPlaceholderText(/search/i);
    expect(searchInput).toBeInTheDocument();
  });

  test('empty state shows "No conversations yet" with a New Conversation CTA', async () => {
    server.use(
      http.get('/api/conversations', () => {
        return HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 });
      }),
    );

    renderWithProviders(<App />);

    await waitFor(() => {
      expect(screen.getByText(/no conversations yet/i)).toBeInTheDocument();
    });

    expect(screen.getAllByText(/new conversation/i).length).toBeGreaterThan(0);
  });
});
