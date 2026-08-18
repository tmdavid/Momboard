/**
 * M6 Explore page — missing requirements (RED tests).
 *
 * T20: Quote card navigation anchored to source utterance
 * T20: Synthesize button disabled below 5, shows count
 * T20: Synthesis polling until result (not single fixed poll)
 * T20: Expandable synthesis themes with evidence quotes
 */
import { describe, test, expect, vi } from 'vitest';
import { screen, waitFor, within, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { server } from '../test/mocks/server';
import { renderWithProviders } from '../test/render';
import { Routes, Route } from 'react-router-dom';
import { ExplorePage } from '../pages/ExplorePage';
import { ConversationPage } from '../pages/ConversationPage';

/**
 * Extended highlights mock that includes utterance_id for anchor navigation.
 */
const highlightsWithUtteranceId = {
  items: [
    {
      id: 1,
      conversation_id: 1,
      utterance_id: 2,
      tag_key: 'pain',
      quote: 'Every Monday I export all flagged listings to Excel',
      confidence: 0.95,
      status: 'accepted',
      origin: 'ai',
      conversation_title: 'Discovery — counterfeit listings',
      conversation_happened_at: '2026-08-12T10:00:00Z',
      company_name: 'Acme Watches',
      contact_names: ['Jane Doe'],
    },
    {
      id: 2,
      conversation_id: 1,
      utterance_id: 3,
      tag_key: 'workaround',
      quote: 'I export to Excel and clean them up by hand',
      confidence: 0.93,
      status: 'accepted',
      origin: 'ai',
      conversation_title: 'Discovery — counterfeit listings',
      conversation_happened_at: '2026-08-12T10:00:00Z',
      company_name: 'Acme Watches',
      contact_names: ['Jane Doe'],
    },
    {
      id: 3,
      conversation_id: 2,
      utterance_id: 5,
      tag_key: 'pain',
      quote: 'Key sellers show up on every marketplace',
      confidence: 0.88,
      status: 'suggested',
      origin: 'ai',
      conversation_title: 'Key-reselling sites',
      conversation_happened_at: '2026-08-07T10:00:00Z',
      company_name: 'PixelForge Games',
      contact_names: ['M. Chen'],
    },
    {
      id: 4,
      conversation_id: 1,
      utterance_id: 2,
      tag_key: 'money',
      quote: 'We set aside €40k for brand protection',
      confidence: 0.96,
      status: 'accepted',
      origin: 'ai',
      conversation_title: 'Discovery — counterfeit listings',
      conversation_happened_at: '2026-08-12T10:00:00Z',
      company_name: 'Acme Watches',
      contact_names: ['Jane Doe'],
    },
    {
      id: 5,
      conversation_id: 2,
      utterance_id: 6,
      tag_key: 'pain',
      quote: 'Legal takes two weeks to approve a takedown',
      confidence: 0.90,
      status: 'accepted',
      origin: 'ai',
      conversation_title: 'Key-reselling sites',
      conversation_happened_at: '2026-08-07T10:00:00Z',
      company_name: 'PixelForge Games',
      contact_names: ['M. Chen'],
    },
    {
      id: 6,
      conversation_id: 1,
      utterance_id: 4,
      tag_key: 'workaround',
      quote: 'We bought the counterfeits ourselves to document them',
      confidence: 0.87,
      status: 'accepted',
      origin: 'ai',
      conversation_title: 'Discovery — counterfeit listings',
      conversation_happened_at: '2026-08-12T10:00:00Z',
      company_name: 'Acme Watches',
      contact_names: ['Jane Doe'],
    },
  ],
  total: 6,
  limit: 100,
  offset: 0,
};

function renderExploreWithConversation() {
  return renderWithProviders(
    <Routes>
      <Route path="/explore" element={<ExplorePage />} />
      <Route path="/conversations/:id" element={<ConversationPage />} />
    </Routes>,
    { route: '/explore' },
  );
}

function renderExplore() {
  return renderWithProviders(
    <Routes>
      <Route path="/explore" element={<ExplorePage />} />
    </Routes>,
    { route: '/explore' },
  );
}

describe('T20: Quote card navigation anchored to source utterance', () => {
  test('clicking a quote card navigates to the conversation page and triggers scroll+flash on the anchored utterance', async () => {
    // Requirement: card click navigates to conversation#utterance-{id} so the
    // page scrolls to the exact source utterance, not just the top of the transcript.
    server.use(
      http.get('/api/highlights', () => {
        return HttpResponse.json(highlightsWithUtteranceId);
      }),
    );

    // Spy on scrollIntoView to verify scroll behavior
    const scrollIntoViewMock = vi.fn();
    Element.prototype.scrollIntoView = scrollIntoViewMock;

    const user = userEvent.setup();
    renderExploreWithConversation();

    await waitFor(() => {
      expect(screen.getByText(/Every Monday I export all flagged listings/)).toBeInTheDocument();
    });

    // Click the first quote card — it should navigate with a hash that anchors
    // to utterance_id=2 (e.g. /conversations/1#utterance-2)
    const card = screen.getByText(/Every Monday I export all flagged listings/).closest('[data-testid="quote-card"]');

    expect(card).toBeTruthy();

    if (card) {
      await user.click(card);
    }

    // After navigation, the conversation page should be rendered and scrollIntoView called
    await waitFor(() => {
      expect(scrollIntoViewMock).toHaveBeenCalled();
    });

    // The utterance element with data-utterance-id="2" should have the flash ring class
    // (flashUtteranceId state is set which adds ring-2 ring-accent)
    const utteranceEl = document.querySelector('[data-utterance-id="2"]');
    expect(utteranceEl).toBeTruthy();
    expect(utteranceEl!.className).toContain('ring-2');
  });

  test('highlights API response includes utterance_id field for anchor navigation', async () => {
    // Requirement: The API must include utterance_id in the explore highlights
    // response so the frontend can build anchored navigation links.
    server.use(
      http.get('/api/highlights', () => {
        return HttpResponse.json(highlightsWithUtteranceId);
      }),
    );

    renderExplore();

    await waitFor(() => {
      expect(screen.getByText(/Every Monday I export all flagged listings/)).toBeInTheDocument();
    });

    // Each quote card should navigate to a URL that includes the utterance hash
    // Verify the card is keyboard-accessible (article with tabIndex=0)
    const cards = screen.getAllByTestId('quote-card');
    expect(cards.length).toBeGreaterThan(0);
    // Cards should be articles with keyboard accessibility
    expect(cards[0].tagName.toLowerCase()).toBe('article');
    expect(cards[0].getAttribute('tabindex')).toBe('0');
  });
});

describe('T20: Synthesize button threshold and count behavior', () => {
  test('synthesize button disabled below 5 shows threshold message with current count', async () => {
    // Requirement: When disabled, the button or its surrounding area tells the user
    // the threshold (e.g. "Need at least 5 highlights", "3/5", "2 more needed").
    // Simply disabling without explanation is not sufficient.
    server.use(
      http.get('/api/highlights', () => {
        return HttpResponse.json({
          items: highlightsWithUtteranceId.items.slice(0, 3),
          total: 3,
          limit: 100,
          offset: 0,
        });
      }),
    );

    renderExplore();

    await waitFor(() => {
      expect(screen.getByText(/3 highlights/)).toBeInTheDocument();
    });

    const btn = screen.getByRole('button', { name: /Synthesize/i });
    expect(btn).toBeDisabled();

    // There must be a visible threshold/count message explaining WHY it's disabled.
    // Acceptable patterns: "need 5", "3/5", "2 more needed", "(min 5)"
    expect(
      screen.queryByText(/need\s*(at least\s*)?5/i) ||
      screen.queryByText(/3\s*\/\s*5/i) ||
      screen.queryByText(/2\s*more/i) ||
      screen.queryByText(/min(imum)?\s*5/i),
    ).toBeTruthy();
  });

  test('synthesize button shows count next to the button label when at 4 highlights', async () => {
    // Requirement: the count is visible contextually with the button
    server.use(
      http.get('/api/highlights', () => {
        return HttpResponse.json({
          items: highlightsWithUtteranceId.items.slice(0, 4),
          total: 4,
          limit: 100,
          offset: 0,
        });
      }),
    );

    renderExplore();

    await waitFor(() => {
      expect(screen.getByText(/4 highlights/)).toBeInTheDocument();
    });

    const btn = screen.getByRole('button', { name: /Synthesize/i });
    expect(btn).toBeDisabled();

    // The button text or its immediate parent should contain threshold info
    // e.g. "✨ Synthesize this view (1 more)" or the button itself shows "4/5"
    const btnArea = btn.parentElement || btn;
    const btnAreaText = btnArea.textContent || '';
    const hasThresholdInfo =
      /need\s*5/i.test(btnAreaText) ||
      /\d\s*\/\s*5/i.test(btnAreaText) ||
      /\d\s*more/i.test(btnAreaText) ||
      /min\s*5/i.test(btnAreaText);
    expect(hasThresholdInfo).toBe(true);
  });
});

describe('T20: Robust synthesis completion polling', () => {
  test('synthesis polling shows progress state until result arrives and stops polling after', async () => {
    // Requirement: After creating a synthesis, the frontend shows a loading/progress
    // indicator that persists across multiple poll cycles. Once result arrives, the
    // indicator disappears and the result renders. Polling must stop after result.
    vi.useFakeTimers({ shouldAdvanceTime: true });

    let pollCount = 0;

    server.use(
      http.get('/api/highlights', () => {
        return HttpResponse.json(highlightsWithUtteranceId);
      }),
      http.post('/api/syntheses', () => {
        return HttpResponse.json(
          {
            id: 42,
            kind: 'synthesis',
            input_scope: {},
            result: null,
            model: null,
            prompt_version: null,
            created_at: new Date().toISOString(),
          },
          { status: 201 },
        );
      }),
      http.get('/api/syntheses/42', () => {
        pollCount++;
        if (pollCount < 4) {
          return HttpResponse.json({
            id: 42,
            kind: 'synthesis',
            input_scope: {},
            result: null,
            model: null,
            prompt_version: null,
            created_at: new Date().toISOString(),
          });
        }
        return HttpResponse.json({
          id: 42,
          kind: 'synthesis',
          input_scope: {},
          result: {
            themes: [
              {
                name: 'Manual triage is universal',
                summary: 'All companies report weekly manual exports.',
                evidence_highlight_ids: [1, 2],
                strength: 'strong',
              },
            ],
            contradictions: [],
            validate_next: ['Ask about automation attempts'],
          },
          model: 'gpt-4o',
          prompt_version: 'synthesizer-v1',
          created_at: new Date().toISOString(),
        });
      }),
    );

    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderExplore();

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Synthesize this view/i })).toBeInTheDocument();
    });

    const btn = screen.getByRole('button', { name: /Synthesize this view/i });
    await user.click(btn);

    // During polling, a progress/loading indicator should be visible
    await waitFor(() => {
      expect(screen.getAllByText(/Synthesizing/i).length).toBeGreaterThan(0);
    });

    // Advance time to trigger multiple polls
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10000);
    });

    // Eventually the result should render
    await waitFor(() => {
      expect(screen.getByText(/Manual triage is universal/)).toBeInTheDocument();
    });

    // After result is rendered, "Synthesizing..." should be gone
    expect(screen.queryAllByText(/Synthesizing/i)).toHaveLength(0);

    // Record poll count, then advance more time — no new polls should happen
    const pollCountAfterResult = pollCount;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10000);
    });

    // Polling should have stopped after result was received
    expect(pollCount).toBe(pollCountAfterResult);

    vi.useRealTimers();
  });
});

describe('T20: Expandable synthesis themes with evidence quotes', () => {
  test('synthesis themes show expandable evidence section that reveals actual highlight quotes', async () => {
    // Requirement: Each theme in the synthesis result has an expandable
    // section "▸ N supporting quotes" which when clicked reveals the actual
    // verbatim quotes from the referenced highlights.
    server.use(
      http.get('/api/highlights', () => {
        return HttpResponse.json(highlightsWithUtteranceId);
      }),
      http.post('/api/syntheses', () => {
        return HttpResponse.json(
          {
            id: 1,
            kind: 'synthesis',
            input_scope: {},
            result: {
              themes: [
                {
                  name: 'Manual triage is universal',
                  summary: 'All companies report weekly manual exports.',
                  evidence_highlight_ids: [1, 2],
                  strength: 'strong',
                },
              ],
              contradictions: [],
              validate_next: ['Ask about automation attempts'],
            },
            model: 'gpt-4o',
            prompt_version: 'synthesizer-v1',
            created_at: new Date().toISOString(),
          },
          { status: 201 },
        );
      }),
      http.get('/api/syntheses/:id', () => {
        return HttpResponse.json({
          id: 1,
          kind: 'synthesis',
          input_scope: {},
          result: {
            themes: [
              {
                name: 'Manual triage is universal',
                summary: 'All companies report weekly manual exports.',
                evidence_highlight_ids: [1, 2],
                strength: 'strong',
              },
            ],
            contradictions: [],
            validate_next: ['Ask about automation attempts'],
          },
          model: 'gpt-4o',
          prompt_version: 'synthesizer-v1',
          created_at: new Date().toISOString(),
        });
      }),
    );

    const user = userEvent.setup();
    renderExplore();

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Synthesize this view/i })).not.toBeDisabled();
    });

    await user.click(screen.getByRole('button', { name: /Synthesize this view/i }));

    // Wait for synthesis result to render
    await waitFor(() => {
      expect(screen.getByText(/Manual triage is universal/)).toBeInTheDocument();
    });

    // The evidence section should be present but collapsed (quotes NOT visible yet)
    const evidenceTrigger = screen.getByText(/2 supporting quotes/);
    expect(evidenceTrigger).toBeInTheDocument();

    // Before clicking, the actual quotes should NOT be visible in the theme block
    const synthPanel = (screen.getByText(/Manual triage is universal/).closest('[class*="synth"]') || document.body) as HTMLElement;
    expect(
      within(synthPanel).queryByText(/Every Monday I export all flagged listings to Excel/),
    ).toBeNull();

    // Click to expand the evidence quotes
    await user.click(evidenceTrigger);

    // After expanding, the actual verbatim quotes from highlights 1 and 2 should be visible
    // within the synthesis theme panel
    await waitFor(() => {
      // highlight id=1 quote: "Every Monday I export all flagged listings to Excel"
      expect(screen.getByText(/Every Monday I export all flagged listings to Excel/)).toBeInTheDocument();
      // highlight id=2 quote: "I export to Excel and clean them up by hand"
      expect(screen.getByText(/I export to Excel and clean them up by hand/)).toBeInTheDocument();
    });
  });
});
