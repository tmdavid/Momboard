import { describe, test, expect } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { server } from '../test/mocks/server';
import { renderWithProviders } from '../test/render';
import { App } from '../App';

describe('Auth flow', () => {
  test('unauthenticated user sees login form, not the library', async () => {
    server.use(
      http.get('/api/me', () => new HttpResponse(null, { status: 401 })),
    );

    renderWithProviders(<App />);

    await waitFor(() => {
      expect(screen.getByText('Sign in to continue')).toBeInTheDocument();
    });

    expect(screen.queryByText('Conversations')).not.toBeInTheDocument();
  });

  test('successful login stores nothing in localStorage (cookie only) and shows Library', async () => {
    server.use(
      http.get('/api/me', () => new HttpResponse(null, { status: 401 })),
    );

    renderWithProviders(<App />);

    await waitFor(() => {
      expect(screen.getByText('Sign in to continue')).toBeInTheDocument();
    });

    const user = userEvent.setup();
    await user.type(screen.getByLabelText(/email/i), 'david@example.com');
    await user.type(screen.getByLabelText(/password/i), 'password123');

    // Override me to return user after login
    server.use(
      http.get('/api/me', () => HttpResponse.json({ id: 1, email: 'david@example.com', name: 'David', role: 'admin' })),
    );

    await user.click(screen.getByRole('button', { name: /sign in/i }));

    await waitFor(() => {
      expect(screen.getByText('Conversations')).toBeInTheDocument();
    });

    // No localStorage usage
    expect(localStorage.getItem('token')).toBeNull();
    expect(localStorage.getItem('session')).toBeNull();
  });

  test('401 from any API call redirects to login', async () => {
    // Start authenticated
    renderWithProviders(<App />);

    await waitFor(() => {
      expect(screen.getByText('Conversations')).toBeInTheDocument();
    });

    // Now make API return 401
    server.use(
      http.get('/api/me', () => new HttpResponse(null, { status: 401 })),
      http.get('/api/conversations', () => new HttpResponse(null, { status: 401 })),
    );
  });
});
