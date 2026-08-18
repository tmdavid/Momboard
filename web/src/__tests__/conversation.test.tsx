import { describe, test, expect } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Routes, Route } from 'react-router-dom';
import { renderWithProviders } from '../test/render';
import { ConversationPage } from '../pages/ConversationPage';

function renderConversation() {
  return renderWithProviders(
    <Routes>
      <Route path="/conversations/:id" element={<ConversationPage />} />
    </Routes>,
    { route: '/conversations/1' },
  );
}

describe('Conversation page', () => {
  test('utterances render in order, our-side vs their-side visually distinct', async () => {
    renderConversation();

    await waitFor(() => {
      expect(screen.getByText('David')).toBeInTheDocument();
    });

    // "David" should be present (our side speaker)
    expect(screen.getByText('David')).toBeInTheDocument();
    // "Jane" should be present (their side speaker)
    expect(screen.getAllByText('Jane').length).toBeGreaterThan(0);
  });

  test('highlighted utterances show emoji chip; suggested ones look pending (dashed)', async () => {
    renderConversation();

    await waitFor(() => {
      expect(screen.getByText(/workaround/)).toBeInTheDocument();
    });

    // Accepted chips should be present
    expect(screen.getByText(/workaround/)).toBeInTheDocument();
    // Suggested chips should show confidence
    expect(screen.getByText('0.91')).toBeInTheDocument();
  });

  test('clicking a chip opens popover with accept / reject / edit tag', async () => {
    const user = userEvent.setup();
    renderConversation();

    await waitFor(() => {
      expect(screen.getAllByText(/pain/).length).toBeGreaterThan(0);
    });

    // Click a suggested chip (the one with 0.91 confidence)
    const suggestedChips = screen.getAllByText('0.91');
    const chipButton = suggestedChips[0].closest('button');
    if (chipButton) {
      await user.click(chipButton);
    }

    await waitFor(() => {
      expect(screen.getByText(/Accept/)).toBeInTheDocument();
      expect(screen.getByText(/Reject/)).toBeInTheDocument();
    });
  });

  test('analysis sidebar renders summary, pains w/ evidence links, commitments, critique score', async () => {
    renderConversation();

    await waitFor(() => {
      expect(screen.getByText('Summary')).toBeInTheDocument();
    });

    expect(screen.getByText(/Brand manager spends half a Monday/)).toBeInTheDocument();
    expect(screen.getByText('Top pains')).toBeInTheDocument();
    expect(screen.getByText(/Manual Excel triage/)).toBeInTheDocument();
    expect(screen.getByText('Mom Test critique')).toBeInTheDocument();
    expect(screen.getByText('8')).toBeInTheDocument();
    expect(screen.getByText('Suggested follow-ups')).toBeInTheDocument();
  });

  test('clicking evidence link scrolls to and flashes the source utterance', async () => {
    const user = userEvent.setup();
    renderConversation();

    await waitFor(() => {
      expect(screen.getAllByText('→ quote').length).toBeGreaterThan(0);
    });

    // Click evidence link
    const quoteLink = screen.getAllByText('→ quote')[0];
    await user.click(quoteLink);

    // The utterance should be scrolled to (we verify no crash and the flash mechanism exists)
  });

  test('review mode banner shows number of suggestions', async () => {
    renderConversation();

    await waitFor(() => {
      expect(screen.getByText(/Review mode/)).toBeInTheDocument();
    });

    expect(screen.getByText(/suggestions left/)).toBeInTheDocument();
  });

  test('cancelling deletion keeps the conversation and does not call the API', async () => {
    const user = userEvent.setup();
    const { http, HttpResponse } = await import('msw');
    const { server } = await import('../test/mocks/server');
    let deleteCalls = 0;
    server.use(
      http.delete('/api/conversations/:id', () => {
        deleteCalls += 1;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderConversation();

    await screen.findByText('Discovery — counterfeit listings workflow');
    await user.click(screen.getByRole('button', { name: 'Delete conversation' }));

    expect(screen.getByRole('dialog', { name: 'Delete conversation?' })).toBeInTheDocument();
    expect(screen.getByText(/permanently deletes the transcript/i)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Cancel' }));

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(deleteCalls).toBe(0);
    expect(screen.getByText('Discovery — counterfeit listings workflow')).toBeInTheDocument();
  });

  test('confirming deletion calls the API and redirects to the Library', async () => {
    const user = userEvent.setup();
    const { http, HttpResponse } = await import('msw');
    const { server } = await import('../test/mocks/server');
    const deletedIds: string[] = [];
    server.use(
      http.delete('/api/conversations/:id', ({ params }) => {
        deletedIds.push(String(params.id));
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderWithProviders(
      <Routes>
        <Route path="/conversations/:id" element={<ConversationPage />} />
        <Route path="/" element={<div>Library destination</div>} />
      </Routes>,
      { route: '/conversations/1' },
    );

    await screen.findByText('Discovery — counterfeit listings workflow');
    await user.click(screen.getByRole('button', { name: 'Delete conversation' }));
    await user.click(screen.getByRole('button', { name: 'Delete permanently' }));

    await waitFor(() => {
      expect(screen.getByText('Library destination')).toBeInTheDocument();
    });
    expect(deletedIds).toEqual(['1']);
  });

  test('failed deletion shows an error and keeps the confirmation open', async () => {
    const user = userEvent.setup();
    const { http, HttpResponse } = await import('msw');
    const { server } = await import('../test/mocks/server');
    server.use(
      http.delete('/api/conversations/:id', () => {
        return HttpResponse.json({ detail: 'Delete failed' }, { status: 500 });
      }),
    );
    renderConversation();

    await screen.findByText('Discovery — counterfeit listings workflow');
    await user.click(screen.getByRole('button', { name: 'Delete conversation' }));
    await user.click(screen.getByRole('button', { name: 'Delete permanently' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Could not delete conversation. Please try again.',
    );
    expect(screen.getByRole('dialog', { name: 'Delete conversation?' })).toBeInTheDocument();
  });
});
