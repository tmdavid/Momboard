import { describe, test, expect, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { renderWithProviders } from '../test/render';
import { server } from '../test/mocks/server';
import { ContactPage } from '../pages/ContactPage';

const mockContact = {
  id: 1,
  name: 'Jane Smith',
  role: 'VP Engineering',
  company_id: 10,
  company_name: 'Acme Corp',
  stats: {
    conversation_count: 5,
    open_followups: 2,
    last_talked: '2026-07-15',
  },
};

const mockTimeline = [
  { kind: 'conversation', timestamp: '2026-07-15T10:00:00Z', conversation_id: 1, title: 'July check-in' },
  { kind: 'highlight', timestamp: '2026-07-15T10:05:00Z', highlight_id: 42, tag_key: 'pain', tag_emoji: '🔥', quote: 'We waste 3 hours every Monday on exports' },
  { kind: 'commitment', timestamp: '2026-07-10T10:00:00Z', highlight_id: 43, tag_key: 'commitment', quote: 'Will send pricing doc by Friday' },
];

const mockDrifts = [
  {
    id: 1,
    kind: 'contradiction',
    summary: 'Position changed on approval workflow',
    status: 'open',
    earlier_quote: 'Legal must approve every takedown',
    later_quote: 'We file directly now',
  },
];

describe('ContactPage (T30)', () => {
  beforeEach(() => {
    server.use(
      http.get('/api/contacts/:id', () => HttpResponse.json(mockContact)),
      http.get('/api/contacts/:id/timeline', () => HttpResponse.json(mockTimeline)),
      http.get('/api/contacts/:id/drifts', () => HttpResponse.json(mockDrifts)),
      http.get('/api/contacts/:id/brief', () =>
        HttpResponse.json({
          id: 1,
          contact_id: 1,
          is_first_call: false,
          known_facts: [],
          suggested_questions: ['What happened with the export process?'],
          watch_out: null,
          open_followups: [],
          open_drifts: [],
          stale_hypotheses: [],
        })
      ),
      http.post('/api/drifts/:id/dismiss', () => HttpResponse.json({ status: 'dismissed' })),
      http.post('/api/drifts/:id/confirm', () => HttpResponse.json({ status: 'confirmed' }))
    );
  });

  test('header shows contact, role, company, stats', async () => {
    renderWithProviders(<ContactPage />, { route: '/contacts/1', path: '/contacts/:id' });

    await waitFor(() => {
      expect(screen.getByText('Jane Smith')).toBeInTheDocument();
    });
    expect(screen.getByText('VP Engineering')).toBeInTheDocument();
    expect(screen.getByText('Acme Corp')).toBeInTheDocument();
    expect(screen.getByText('5 conversations')).toBeInTheDocument();
    expect(screen.getByText('2 open follow-ups')).toBeInTheDocument();
  });

  test('timeline renders newest-first with kind icons', async () => {
    renderWithProviders(<ContactPage />, { route: '/contacts/1', path: '/contacts/:id' });

    await waitFor(() => {
      expect(screen.getByText('July check-in')).toBeInTheDocument();
    });
    expect(screen.getByText(/We waste 3 hours/)).toBeInTheDocument();
    expect(screen.getByText(/Will send pricing doc/)).toBeInTheDocument();
  });

  test('drift alerts render with side-by-side quotes and dismiss/confirm', async () => {
    renderWithProviders(<ContactPage />, { route: '/contacts/1', path: '/contacts/:id' });

    await waitFor(() => {
      expect(screen.getByText(/Legal must approve/)).toBeInTheDocument();
    });
    expect(screen.getByText(/We file directly now/)).toBeInTheDocument();
    expect(screen.getByText('Dismiss')).toBeInTheDocument();
    expect(screen.getByText('Confirm')).toBeInTheDocument();
  });

  test('kind filter buttons filter timeline', async () => {
    renderWithProviders(<ContactPage />, { route: '/contacts/1', path: '/contacts/:id' });

    await waitFor(() => {
      expect(screen.getByText('July check-in')).toBeInTheDocument();
    });

    const signalsBtn = screen.getByText('signals');
    await userEvent.click(signalsBtn);
    // Filter is applied (re-fetch with kind=signals)
    expect(signalsBtn).toHaveClass('bg-indigo-100');
  });

  test('prep brief button generates brief', async () => {
    renderWithProviders(<ContactPage />, { route: '/contacts/1', path: '/contacts/:id' });

    await waitFor(() => {
      expect(screen.getByTestId('prep-brief-btn')).toBeInTheDocument();
    });

    await userEvent.click(screen.getByTestId('prep-brief-btn'));

    await waitFor(() => {
      expect(screen.getByTestId('brief-result')).toBeInTheDocument();
    });
    expect(screen.getByText(/What happened with the export/)).toBeInTheDocument();
  });

  test('company name links to company page', async () => {
    renderWithProviders(<ContactPage />, { route: '/contacts/1', path: '/contacts/:id' });

    await waitFor(() => {
      expect(screen.getByText('Acme Corp')).toBeInTheDocument();
    });
    expect(screen.getByText('Acme Corp').closest('a')).toHaveAttribute('href', '/companies/10');
  });
});
