import { describe, test, expect } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { server } from '../test/mocks/server';
import { renderWithProviders } from '../test/render';
import { Routes, Route } from 'react-router-dom';
import { ConversationPage } from '../pages/ConversationPage';

function renderConversation() {
  return renderWithProviders(
    <Routes>
      <Route path="/conversations/:id" element={<ConversationPage />} />
    </Routes>,
    { route: '/conversations/1' },
  );
}

describe('Notes panel', () => {
  test('notes panel toggles open, shows markdown editor + preview tabs', async () => {
    const user = userEvent.setup();
    renderConversation();

    await waitFor(() => {
      expect(screen.getByText('📝 Notes')).toBeInTheDocument();
    });

    await user.click(screen.getByText('📝 Notes'));

    expect(screen.getByText('Write')).toBeInTheDocument();
    expect(screen.getByText('Preview')).toBeInTheDocument();
  });

  test('autosaves after typing stops; shows saving indicator', async () => {
    const user = userEvent.setup();
    renderConversation();

    await waitFor(() => {
      expect(screen.getByText('📝 Notes')).toBeInTheDocument();
    });

    await user.click(screen.getByText('📝 Notes'));

    await waitFor(() => {
      expect(screen.getByText('Saved')).toBeInTheDocument();
    });

    const textarea = screen.getByRole('textbox');
    await user.type(textarea, ' new content');

    // Should show "Saving…" immediately after typing
    expect(screen.getByText('Saving…')).toBeInTheDocument();

    // After debounce + mutation resolves, it shows Saved again
    await waitFor(() => {
      expect(screen.getByText('Saved')).toBeInTheDocument();
    }, { timeout: 3000 });
  });

  test('409 conflict shows "someone else edited" banner with reload option', async () => {
    server.use(
      http.put('/api/conversations/:id/note', () => {
        return new HttpResponse(JSON.stringify({ detail: 'Note was modified by another user.' }), { status: 409 });
      }),
    );

    const user = userEvent.setup();
    renderConversation();

    await waitFor(() => {
      expect(screen.getByText('📝 Notes')).toBeInTheDocument();
    });

    await user.click(screen.getByText('📝 Notes'));

    await waitFor(() => {
      expect(screen.getByRole('textbox')).toBeInTheDocument();
    });

    const textarea = screen.getByRole('textbox');
    await user.type(textarea, ' edited');

    await waitFor(() => {
      expect(screen.getByText(/Conflict/)).toBeInTheDocument();
    }, { timeout: 3000 });

    expect(screen.getByText('Reload')).toBeInTheDocument();
  });
});
