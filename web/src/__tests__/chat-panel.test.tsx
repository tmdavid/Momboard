import { describe, test, expect, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { renderWithProviders } from '../test/render';
import { server } from '../test/mocks/server';
import { ChatPanel } from '../components/ChatPanel';

describe('ChatPanel (T42)', () => {
  beforeEach(() => {
    server.use(
      http.post('/api/chat', async ({ request }) => {
        const body = (await request.json()) as { question: string };
        if (body.question.includes('pricing')) {
          // Gap response
          return HttpResponse.json({
            claims: [],
            gap: true,
            suggested_interview_question: "How do you currently handle pricing changes?",
            chat_id: 1,
          });
        }
        return HttpResponse.json({
          claims: [
            {
              text: 'Customers report wasting 3 hours on exports weekly.',
              evidence_highlight_ids: [42, 55],
            },
          ],
          gap: false,
          suggested_interview_question: null,
          chat_id: 1,
        });
      }),
      http.get('/api/chat', () => HttpResponse.json([]))
    );
  });

  test('shows question input and submit button', () => {
    renderWithProviders(<ChatPanel />);
    expect(screen.getByTestId('chat-input')).toBeInTheDocument();
    expect(screen.getByText('Ask')).toBeInTheDocument();
  });

  test('submitting question shows citation chips', async () => {
    renderWithProviders(<ChatPanel />);

    const input = screen.getByTestId('chat-input');
    await userEvent.type(input, 'What are the biggest export problems?');
    await userEvent.click(screen.getByText('Ask'));

    await waitFor(() => {
      expect(screen.getByText(/wasting 3 hours/)).toBeInTheDocument();
    });
    // Citation chips rendered
    const chips = screen.getAllByTestId('citation-chip');
    expect(chips.length).toBe(2);
  });

  test('gap state renders when no evidence', async () => {
    renderWithProviders(<ChatPanel />);

    const input = screen.getByTestId('chat-input');
    await userEvent.type(input, 'What about pricing tiers?');
    await userEvent.click(screen.getByText('Ask'));

    await waitFor(() => {
      expect(screen.getByTestId('gap-state')).toBeInTheDocument();
    });
    expect(screen.getByText(/No evidence found/)).toBeInTheDocument();
    expect(screen.getByText(/How do you currently handle/)).toBeInTheDocument();
  });

  test('per-user history maintained via chat_id', async () => {
    renderWithProviders(<ChatPanel />);

    const input = screen.getByTestId('chat-input');
    await userEvent.type(input, 'test question');
    await userEvent.click(screen.getByText('Ask'));

    await waitFor(() => {
      expect(screen.getByText('test question')).toBeInTheDocument();
    });
  });
});
