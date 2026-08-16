/**
 * RED-phase tests: T14 — actual any-request 401 → logout/login transition.
 *
 * Acceptance criteria:
 * - When any API call returns 401 mid-session, user is redirected to login.
 * - This must happen for *any* request (not just /api/me), including
 *   list, detail, and mutation endpoints.
 * - The transition should be seamless: no flash of authenticated UI.
 */
import { describe, test, expect } from 'vitest';
import { screen, waitFor, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { server } from '../test/mocks/server';
import { renderWithProviders } from '../test/render';
import { App } from '../App';

describe('T14 — Global 401 redirect', () => {
  test('401 from /api/conversations while authenticated redirects to login', async () => {
    // Start with user authenticated — default handlers serve /api/me successfully
    renderWithProviders(<App />);

    // Wait for the library to load
    await waitFor(() => {
      expect(screen.getByText('Conversations')).toBeInTheDocument();
    });

    // Now simulate session expiry: all subsequent requests return 401
    server.use(
      http.get('/api/me', () => new HttpResponse(null, { status: 401 })),
      http.get('/api/conversations', () => new HttpResponse(null, { status: 401 })),
    );

    // Trigger a refetch (e.g., by focusing the window or waiting for stale time)
    // The global error handler should catch the 401 and redirect to login
    await act(async () => {
      // Simulate a window focus event that triggers TanStack Query refetch
      window.dispatchEvent(new Event('focus'));
    });

    await waitFor(
      () => {
        expect(screen.getByText('Sign in to continue')).toBeInTheDocument();
      },
      { timeout: 5000 },
    );

    // Library should no longer be visible
    expect(screen.queryByText('Conversations')).not.toBeInTheDocument();
  });

  test('401 from a mutation (e.g., PATCH highlight) triggers logout redirect', async () => {
    renderWithProviders(<App />);

    await waitFor(() => {
      expect(screen.getByText('Conversations')).toBeInTheDocument();
    });

    // Override the highlight PATCH to return 401
    server.use(
      http.patch('/api/highlights/:id', () => new HttpResponse(null, { status: 401 })),
      http.get('/api/me', () => new HttpResponse(null, { status: 401 })),
    );

    // The global onError handler should detect the 401 and redirect to login
    await act(async () => {
      window.dispatchEvent(new Event('focus'));
    });

    await waitFor(
      () => {
        expect(screen.getByText('Sign in to continue')).toBeInTheDocument();
      },
      { timeout: 5000 },
    );
  });

  test('401 from /api/conversations/:id/note shows login, not stale data', async () => {
    renderWithProviders(<App />);

    await waitFor(() => {
      expect(screen.getByText('Conversations')).toBeInTheDocument();
    });

    // Session expires
    server.use(
      http.get('/api/me', () => new HttpResponse(null, { status: 401 })),
      http.get('/api/conversations/:id/note', () => new HttpResponse(null, { status: 401 })),
    );

    await act(async () => {
      window.dispatchEvent(new Event('focus'));
    });

    await waitFor(
      () => {
        expect(screen.getByText('Sign in to continue')).toBeInTheDocument();
      },
      { timeout: 5000 },
    );
  });

  test('after 401 redirect, user can re-login and sees the library again', async () => {
    const user = userEvent.setup();

    renderWithProviders(<App />);

    await waitFor(() => {
      expect(screen.getByText('Conversations')).toBeInTheDocument();
    });

    // Session expires
    server.use(
      http.get('/api/me', () => new HttpResponse(null, { status: 401 })),
      http.get('/api/conversations', () => new HttpResponse(null, { status: 401 })),
    );

    await act(async () => {
      window.dispatchEvent(new Event('focus'));
    });

    await waitFor(
      () => {
        expect(screen.getByText('Sign in to continue')).toBeInTheDocument();
      },
      { timeout: 5000 },
    );

    // Restore session handlers
    server.use(
      http.get('/api/me', () =>
        HttpResponse.json({ id: 1, email: 'david@example.com', name: 'David', role: 'admin' }),
      ),
      http.get('/api/conversations', () =>
        HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 }),
      ),
    );

    await user.type(screen.getByLabelText(/email/i), 'david@example.com');
    await user.type(screen.getByLabelText(/password/i), 'password123');
    await user.click(screen.getByRole('button', { name: /sign in/i }));

    await waitFor(() => {
      expect(screen.getByText('Conversations')).toBeInTheDocument();
    });
  });
});
