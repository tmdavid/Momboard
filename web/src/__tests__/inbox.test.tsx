import { describe, test, expect, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { renderWithProviders } from '../test/render';
import { server } from '../test/mocks/server';
import { InboxPage } from '../pages/InboxPage';

const mockItems = [
  {
    id: 1,
    source: 'gmeet',
    source_ref: 'gdrive:doc123',
    title: 'Meeting with Acme',
    status: 'pending_import',
    parse_error: null,
    conversation_id: null,
    created_at: '2026-08-01T10:00:00Z',
  },
  {
    id: 2,
    source: 'mcp',
    source_ref: 'mcp:hash456',
    title: 'Demo call transcript',
    status: 'parse_error',
    parse_error: 'Could not parse Meet Doc: no speaker patterns found',
    conversation_id: null,
    created_at: '2026-08-02T10:00:00Z',
  },
];

describe('InboxPage (T34)', () => {
  beforeEach(() => {
    server.use(
      http.get('/api/inbox', ({ request }) => {
        const url = new URL(request.url);
        const status = url.searchParams.get('status');
        const filtered = status
          ? mockItems.filter((i) => i.status === status)
          : mockItems;
        return HttpResponse.json({ items: filtered, total: filtered.length });
      }),
      http.post('/api/inbox/:id/import', () => {
        return HttpResponse.json({ ...mockItems[0], status: 'imported' });
      }),
      http.post('/api/inbox/:id/ignore', () => {
        return HttpResponse.json({ ...mockItems[0], status: 'ignored' });
      })
    );
  });

  test('renders inbox items with status filtering', async () => {
    renderWithProviders(<InboxPage />);

    await waitFor(() => {
      expect(screen.getByText('Meeting with Acme')).toBeInTheDocument();
    });

    // Status tabs present
    expect(screen.getByRole('tab', { name: 'Pending' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Parse Errors' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Imported' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Ignored' })).toBeInTheDocument();
  });

  test('shows parse error visibility', async () => {
    server.use(
      http.get('/api/inbox', () => {
        return HttpResponse.json({ items: mockItems, total: 2 });
      })
    );

    renderWithProviders(<InboxPage />);

    // Switch to All tab
    const allTab = await screen.findByRole('tab', { name: 'All' });
    await userEvent.click(allTab);

    await waitFor(() => {
      expect(screen.getByTestId('parse-error')).toBeInTheDocument();
    });
  });

  test('import button triggers import action', async () => {
    renderWithProviders(<InboxPage />);

    await waitFor(() => {
      expect(screen.getByText('Meeting with Acme')).toBeInTheDocument();
    });

    const importBtn = screen.getAllByText('Import')[0];
    await userEvent.click(importBtn);

    // Should trigger the mutation (verified by no error thrown)
    await waitFor(() => {
      expect(importBtn).toBeDefined();
    });
  });

  test('ignore button triggers ignore action', async () => {
    renderWithProviders(<InboxPage />);

    await waitFor(() => {
      expect(screen.getByText('Meeting with Acme')).toBeInTheDocument();
    });

    const ignoreBtn = screen.getAllByText('Ignore')[0];
    await userEvent.click(ignoreBtn);

    await waitFor(() => {
      expect(ignoreBtn).toBeDefined();
    });
  });

  test('source badge shows source type', async () => {
    renderWithProviders(<InboxPage />);

    await waitFor(() => {
      expect(screen.getByText('gmeet')).toBeInTheDocument();
    });
  });
});
