/**
 * T45: Summaries tab — lists background syntheses, save/discard, processing chip.
 */
import { describe, test, expect } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { server } from '../test/mocks/server';
import { renderWithProviders } from '../test/render';
import { SummariesPage } from '../pages/SummariesPage';

function doneSynthesis(overrides: Record<string, unknown> = {}) {
  return {
    id: 1,
    kind: 'synthesis',
    input_scope: { tags: ['pain', 'workaround'] },
    result: {
      themes: [
        { name: 'Manual triage is universal', summary: 'Weekly manual exports everywhere.', evidence_highlight_ids: [1, 2], strength: 'strong' },
      ],
      contradictions: [],
      validate_next: ['Ask about automation attempts'],
    },
    model: 'gpt-4o',
    prompt_version: 'synthesizer-v1',
    saved: false,
    status: 'done',
    error: null,
    created_at: new Date().toISOString(),
    ...overrides,
  };
}

describe('SummariesPage', () => {
  test('renders a completed synthesis with its themes', async () => {
    server.use(
      http.get('/api/syntheses', () => HttpResponse.json({ items: [doneSynthesis()], total: 1 })),
    );

    renderWithProviders(<SummariesPage />, { route: '/summaries' });

    await waitFor(() => {
      expect(screen.getByText(/Manual triage is universal/)).toBeInTheDocument();
    });
    expect(screen.getByText(/Validate next/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Save/i })).toBeInTheDocument();
  });

  test('shows a processing chip for a pending synthesis', async () => {
    server.use(
      http.get('/api/syntheses', () =>
        HttpResponse.json({
          items: [doneSynthesis({ id: 5, result: null, status: 'queued' })],
          total: 1,
        }),
      ),
    );

    renderWithProviders(<SummariesPage />, { route: '/summaries' });

    await waitFor(() => {
      expect(screen.getByText(/Running/i)).toBeInTheDocument();
    });
    // Pending syntheses cannot be saved yet.
    expect(screen.queryByRole('button', { name: /Save/i })).toBeNull();
  });

  test('save toggles the synthesis saved state', async () => {
    let patched: { id: string; saved: boolean } | null = null;
    server.use(
      http.get('/api/syntheses', () => HttpResponse.json({ items: [doneSynthesis()], total: 1 })),
      http.patch('/api/syntheses/:id', async ({ request, params }) => {
        const body = (await request.json()) as { saved: boolean };
        patched = { id: String(params.id), saved: body.saved };
        return HttpResponse.json(doneSynthesis({ saved: body.saved }));
      }),
    );

    const user = userEvent.setup();
    renderWithProviders(<SummariesPage />, { route: '/summaries' });

    await waitFor(() => expect(screen.getByRole('button', { name: /Save/i })).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: /Save/i }));

    await waitFor(() => expect(patched).toEqual({ id: '1', saved: true }));
  });

  test('discard deletes the synthesis', async () => {
    let deleted = false;
    server.use(
      http.get('/api/syntheses', () =>
        HttpResponse.json({ items: deleted ? [] : [doneSynthesis()], total: deleted ? 0 : 1 }),
      ),
      http.delete('/api/syntheses/:id', () => {
        deleted = true;
        return new HttpResponse(null, { status: 204 });
      }),
    );

    const user = userEvent.setup();
    renderWithProviders(<SummariesPage />, { route: '/summaries' });

    await waitFor(() => expect(screen.getByTestId('summary-card')).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: /Discard summary/i }));

    await waitFor(() => expect(deleted).toBe(true));
  });

  test('empty state when there are no summaries', async () => {
    server.use(
      http.get('/api/syntheses', () => HttpResponse.json({ items: [], total: 0 })),
    );

    renderWithProviders(<SummariesPage />, { route: '/summaries' });

    await waitFor(() => expect(screen.getByTestId('summaries-empty')).toBeInTheDocument());
  });
});
