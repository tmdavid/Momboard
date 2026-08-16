/**
 * RED-phase tests: T17 — Conversation page transcript + review.
 *
 * Acceptance criteria:
 * - Keyboard: j/k moves through suggested highlights, a accepts, x rejects.
 * - Accepting fires PATCH and chip switches to solid immediately (optimistic mutation).
 * - Clicking evidence link scrolls to and flashes the source utterance (ring animation).
 * - Select text in an utterance → 'add highlight' affordance → manual highlight POSTed.
 * - Safe Markdown preview in notes (no XSS via script injection).
 * - Multiple contacts/roles display correctly in conversation detail.
 */
import { describe, test, expect, vi } from 'vitest';
import { screen, waitFor, fireEvent, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { server } from '../test/mocks/server';
import { renderWithProviders } from '../test/render';
import { Routes, Route } from 'react-router-dom';
import { ConversationPage } from '../pages/ConversationPage';

function renderConversation(route = '/conversations/1') {
  return renderWithProviders(
    <Routes>
      <Route path="/conversations/:id" element={<ConversationPage />} />
    </Routes>,
    { route },
  );
}

describe('T17 — Keyboard review navigation', () => {
  test('pressing j moves focus to next suggested highlight', async () => {
    renderConversation();

    await waitFor(() => {
      expect(screen.getByText(/Review mode/)).toBeInTheDocument();
    });

    // Press j to move to the first suggested highlight
    await act(async () => {
      fireEvent.keyDown(window, { key: 'j' });
    });

    // The focused utterance should have an outline (data-utterance-id="3" for suggested highlight id=3)
    await waitFor(() => {
      const utteranceEl = document.querySelector('[data-utterance-id="3"]');
      expect(utteranceEl).not.toBeNull();
      expect(utteranceEl!.className).toContain('outline');
    });
  });

  test('pressing k moves focus to previous suggested highlight', async () => {
    renderConversation();

    await waitFor(() => {
      expect(screen.getByText(/Review mode/)).toBeInTheDocument();
    });

    // Move forward twice
    await act(async () => {
      fireEvent.keyDown(window, { key: 'j' });
    });
    await act(async () => {
      fireEvent.keyDown(window, { key: 'j' });
    });

    // Move back
    await act(async () => {
      fireEvent.keyDown(window, { key: 'k' });
    });

    // Should be back on the first suggested highlight
    await waitFor(() => {
      const utteranceEl = document.querySelector('[data-utterance-id="3"]');
      expect(utteranceEl).not.toBeNull();
      expect(utteranceEl!.className).toContain('outline');
    });
  });

  test('pressing a on focused highlight fires PATCH with status=accepted', async () => {
    const patchRequests: Array<{ id: string; body: unknown }> = [];

    server.use(
      http.patch('/api/highlights/:id', async ({ request, params }) => {
        const body = await request.json();
        patchRequests.push({ id: params.id as string, body });
        return HttpResponse.json({ id: Number(params.id), status: 'accepted', tag_key: 'pain', quote: 'test', confidence: 0.91, origin: 'ai', conversation_id: 1, utterance_id: 3, char_start: null, char_end: null, note: null, created_at: '2026-08-12T12:00:00Z' });
      }),
    );

    renderConversation();

    await waitFor(() => {
      expect(screen.getByText(/Review mode/)).toBeInTheDocument();
    });

    // Focus first suggested
    await act(async () => {
      fireEvent.keyDown(window, { key: 'j' });
    });

    // Accept it
    await act(async () => {
      fireEvent.keyDown(window, { key: 'a' });
    });

    await waitFor(() => {
      expect(patchRequests.length).toBeGreaterThan(0);
    });

    // Verify PATCH was sent with correct data
    const patch = patchRequests[0];
    expect(patch.body).toEqual({ status: 'accepted' });
    // The ID should be one of the suggested highlight IDs (3 or 4)
    expect(['3', '4']).toContain(patch.id);
  });

  test('pressing x on focused highlight fires PATCH with status=rejected', async () => {
    const patchRequests: Array<{ id: string; body: unknown }> = [];

    server.use(
      http.patch('/api/highlights/:id', async ({ request, params }) => {
        const body = await request.json();
        patchRequests.push({ id: params.id as string, body });
        return HttpResponse.json({ id: Number(params.id), status: 'rejected', tag_key: 'pain', quote: 'test', confidence: 0.91, origin: 'ai', conversation_id: 1, utterance_id: 3, char_start: null, char_end: null, note: null, created_at: '2026-08-12T12:00:00Z' });
      }),
    );

    renderConversation();

    await waitFor(() => {
      expect(screen.getByText(/Review mode/)).toBeInTheDocument();
    });

    // Focus first suggested
    await act(async () => {
      fireEvent.keyDown(window, { key: 'j' });
    });

    // Reject it
    await act(async () => {
      fireEvent.keyDown(window, { key: 'x' });
    });

    await waitFor(() => {
      expect(patchRequests.length).toBeGreaterThan(0);
    });

    expect(patchRequests[0].body).toEqual({ status: 'rejected' });
  });

  test('j/k are ignored when focus is in a textarea or input', async () => {
    renderConversation();

    await waitFor(() => {
      expect(screen.getByText(/Review mode/)).toBeInTheDocument();
    });

    // Focus the notes textarea (if it opens)
    const user = userEvent.setup();
    await user.click(screen.getByText('📝 Notes'));

    await waitFor(() => {
      expect(screen.getByRole('textbox')).toBeInTheDocument();
    });

    const textarea = screen.getByRole('textbox');
    await user.click(textarea);

    // Press j in the textarea — should NOT move highlight focus
    await user.keyboard('j');

    // Verify no outline class was added to utterance elements
    const utteranceEl = document.querySelector('[data-utterance-id="3"]');
    // The outline should NOT be present since we're typing in a textbox
    expect(utteranceEl?.className || '').not.toContain('outline-2 outline-accent');
  });
});

describe('T17 — Optimistic mutation on accept/reject', () => {
  test('accepting a chip switches it from dashed (suggested) to solid immediately', async () => {
    renderConversation();

    await waitFor(() => {
      // Suggested chip has dashed border and shows confidence
      expect(screen.getByText('0.91')).toBeInTheDocument();
    });

    // Click the suggested chip to open popover
    const user = userEvent.setup();
    const suggestedChip = screen.getByText('0.91').closest('button');
    expect(suggestedChip).not.toBeNull();
    await user.click(suggestedChip!);

    // Accept from popover
    await waitFor(() => {
      expect(screen.getByText(/Accept/)).toBeInTheDocument();
    });
    await user.click(screen.getByText(/Accept/));

    // Immediately (optimistically), the chip should switch from dashed to solid
    await waitFor(() => {
      // The confidence text should be gone (no longer suggested)
      expect(screen.queryByText('0.91')).not.toBeInTheDocument();
    });

    // The chip should now have solid border styling (border-[#9ec5f4])
    // and no longer have border-dashed
    const painChips = screen.getAllByText(/pain/i).filter(el => el.closest('button'));
    const solidChips = painChips.filter(el => {
      const btn = el.closest('button');
      return btn && !btn.className.includes('dashed');
    });
    expect(solidChips.length).toBeGreaterThan(0);
  });

  test('rejecting a chip removes it from the UI immediately (optimistic)', async () => {
    renderConversation();

    await waitFor(() => {
      expect(screen.getByText('0.91')).toBeInTheDocument();
    });

    const user = userEvent.setup();
    const suggestedChip = screen.getByText('0.91').closest('button');
    await user.click(suggestedChip!);

    await waitFor(() => {
      expect(screen.getByText(/Reject/)).toBeInTheDocument();
    });
    await user.click(screen.getByText(/Reject/));

    // The rejected chip should disappear immediately
    await waitFor(() => {
      // Highlight id=3 had confidence 0.91, it should be gone
      expect(screen.queryByText('0.91')).not.toBeInTheDocument();
    });
  });
});

describe('T17 — Evidence flash', () => {
  test('clicking an evidence link adds flash ring class to the target utterance', async () => {
    renderConversation();

    await waitFor(() => {
      expect(screen.getAllByText('→ quote').length).toBeGreaterThan(0);
    });

    const user = userEvent.setup();
    const quoteLink = screen.getAllByText('→ quote')[0];
    await user.click(quoteLink);

    // The target utterance should have a flash/ring class
    await waitFor(() => {
      // Find utterance elements with the ring/flash animation
      const flashedEl = document.querySelector('[data-utterance-id].ring-2');
      expect(flashedEl).not.toBeNull();
    });
  });

  test('flash ring class is removed after ~1.4s', async () => {
    renderConversation();

    // Wait for all initial queries (including NotesDrawer) to settle before switching to fake timers
    await waitFor(() => {
      expect(screen.getAllByText('→ quote').length).toBeGreaterThan(0);
    });

    // Allow pending microtasks/queries to flush
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });

    vi.useFakeTimers({ shouldAdvanceTime: true });

    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const quoteLink = screen.getAllByText('→ quote')[0];
    await user.click(quoteLink);

    // Flash should be present
    await waitFor(() => {
      const flashedEl = document.querySelector('[data-utterance-id].ring-2');
      expect(flashedEl).not.toBeNull();
    });

    // After 1.4s, flash should be gone
    await act(async () => {
      vi.advanceTimersByTime(1500);
    });

    const flashedEl = document.querySelector('[data-utterance-id].ring-2');
    expect(flashedEl).toBeNull();

    vi.useRealTimers();
  });
});

describe('T17 — Manual highlight via text selection', () => {
  test('selecting text in an utterance shows an "add highlight" affordance', async () => {
    renderConversation();

    await waitFor(() => {
      expect(screen.getByText(/Every Monday I export/)).toBeInTheDocument();
    });

    // Simulate text selection on an utterance
    const utteranceEl = document.querySelector('[data-utterance-id="2"]');
    expect(utteranceEl).not.toBeNull();

    // Create a selection range
    const textNode = utteranceEl!.querySelector('p')!.firstChild!;
    const range = document.createRange();
    range.setStart(textNode, 0);
    range.setEnd(textNode, 20);

    const selection = window.getSelection()!;
    selection.removeAllRanges();
    selection.addRange(range);

    // Trigger mouseup which should show the "add highlight" affordance
    fireEvent.mouseUp(utteranceEl!);

    // Should show an inline affordance (tooltip/button) to add highlight
    await waitFor(() => {
      expect(screen.getByText(/add highlight/i)).toBeInTheDocument();
    });
  });

  test('using the affordance POSTs a manual highlight with selected text', async () => {
    const postRequests: Array<{ body: unknown }> = [];

    server.use(
      http.post('/api/conversations/:id/highlights', async ({ request }) => {
        const body = await request.json();
        postRequests.push({ body });
        return HttpResponse.json(
          { id: 100, conversation_id: 1, utterance_id: 2, tag_key: 'pain', quote: 'Every Monday I expo', char_start: null, char_end: null, note: null, confidence: 1.0, origin: 'human', status: 'accepted', created_at: new Date().toISOString() },
          { status: 201 },
        );
      }),
    );

    renderConversation();

    await waitFor(() => {
      expect(screen.getByText(/Every Monday I export/)).toBeInTheDocument();
    });

    // Simulate text selection
    const utteranceEl = document.querySelector('[data-utterance-id="2"]');
    const textNode = utteranceEl!.querySelector('p')!.firstChild!;
    const range = document.createRange();
    range.setStart(textNode, 0);
    range.setEnd(textNode, 20);

    const selection = window.getSelection()!;
    selection.removeAllRanges();
    selection.addRange(range);

    fireEvent.mouseUp(utteranceEl!);

    // Click the add highlight button and select a tag
    await waitFor(() => {
      expect(screen.getByText(/add highlight/i)).toBeInTheDocument();
    });

    const user = userEvent.setup();
    await user.click(screen.getByText(/add highlight/i));

    // Should show tag selector (not window.prompt)
    await waitFor(() => {
      expect(screen.getByText(/⚡.*pain/i)).toBeInTheDocument();
    });

    await user.click(screen.getByText(/⚡.*pain/i));

    // Verify POST
    await waitFor(() => {
      expect(postRequests.length).toBe(1);
    });

    const body = postRequests[0].body as Record<string, unknown>;
    expect(body.utterance_id).toBe(2);
    expect(body.tag_key).toBe('pain');
    expect(body.quote).toBeTruthy();
  });
});

describe('T17 — Multiple contacts/roles in conversation detail', () => {
  test('conversation detail shows all contacts with their roles', async () => {
    server.use(
      http.get('/api/conversations/:id', () =>
        HttpResponse.json({
          ...mockConversationDetailWithMultipleContacts(),
        }),
      ),
    );

    renderConversation();

    await waitFor(() => {
      expect(screen.getByText('Jane Doe')).toBeInTheDocument();
    });

    // Both contacts should be visible with roles
    expect(screen.getByText(/Jane Doe/)).toBeInTheDocument();
    expect(screen.getByText(/Brand Manager/)).toBeInTheDocument();
    expect(screen.getByText(/John Smith/)).toBeInTheDocument();
    expect(screen.getByText(/CTO/)).toBeInTheDocument();
  });
});

describe('T17 — Safe Markdown preview', () => {
  test('markdown preview does not execute script tags (XSS safe)', async () => {
    const maliciousMd = '# Hello\n\n<script>window.__xss = true;</script>\n\nSafe content';

    server.use(
      http.get('/api/conversations/:id/note', () =>
        HttpResponse.json({
          id: 1,
          conversation_id: 1,
          body_md: maliciousMd,
          updated_by: 1,
          updated_at: '2026-08-12T14:00:00Z',
        }),
      ),
    );

    const user = userEvent.setup();
    renderConversation();

    await waitFor(() => {
      expect(screen.getByText('📝 Notes')).toBeInTheDocument();
    });

    await user.click(screen.getByText('📝 Notes'));

    // Click Preview tab
    await waitFor(() => {
      expect(screen.getByText('Preview')).toBeInTheDocument();
    });
    await user.click(screen.getByText('Preview'));

    // Wait for preview to render
    await waitFor(() => {
      expect(screen.getByText('Safe content')).toBeInTheDocument();
    });

    // Script should NOT have executed
    expect((window as unknown as Record<string, unknown>).__xss).toBeUndefined();

    // The heading should be rendered properly
    expect(screen.getByText('Hello')).toBeInTheDocument();

    // Script tag should not be present in DOM
    const scripts = document.querySelectorAll('script');
    // Only the test runner's scripts, not from markdown
    const markdownScripts = Array.from(scripts).filter(s =>
      s.textContent?.includes('__xss'),
    );
    expect(markdownScripts.length).toBe(0);
  });

  test('markdown preview sanitizes img onerror XSS', async () => {
    const maliciousMd = '![x](x onerror="window.__xss2=true")';

    server.use(
      http.get('/api/conversations/:id/note', () =>
        HttpResponse.json({
          id: 1,
          conversation_id: 1,
          body_md: maliciousMd,
          updated_by: 1,
          updated_at: '2026-08-12T14:00:00Z',
        }),
      ),
    );

    const user = userEvent.setup();
    renderConversation();

    await waitFor(() => {
      expect(screen.getByText('📝 Notes')).toBeInTheDocument();
    });

    await user.click(screen.getByText('📝 Notes'));

    await waitFor(() => {
      expect(screen.getByText('Preview')).toBeInTheDocument();
    });
    await user.click(screen.getByText('Preview'));

    // Wait a bit for any XSS to execute
    await new Promise((r) => setTimeout(r, 100));

    expect((window as unknown as Record<string, unknown>).__xss2).toBeUndefined();
  });
});

// ─── Helpers ───

function mockConversationDetailWithMultipleContacts() {
  return {
    id: 1,
    title: 'Discovery — counterfeit listings workflow',
    happened_at: '2026-08-12T10:00:00Z',
    status: 'ready',
    source: 'upload',
    interviewer: 'David',
    company: { id: 1, name: 'Acme Watches', domain: 'acme.com', notes: null, created_at: '2026-08-01T00:00:00Z' },
    contacts: [
      { id: 1, name: 'Jane Doe', role: 'Brand Manager', email: null, company_id: 1, created_at: '2026-08-01T00:00:00Z' },
      { id: 2, name: 'John Smith', role: 'CTO', email: null, company_id: 1, created_at: '2026-08-01T00:00:00Z' },
    ],
    meta: { deal_stage: 'discovery', segment: 'enterprise' },
    created_at: '2026-08-12T10:00:00Z',
    utterances: [
      { id: 1, idx: 0, speaker_label: 'David', speaker_side: 'us', text: 'How do you handle infringing listings today?', start_ms: null },
      { id: 2, idx: 1, speaker_label: 'Jane', speaker_side: 'them', text: 'Every Monday I export all flagged listings to Excel.', start_ms: null },
    ],
    highlights: [
      { id: 1, conversation_id: 1, utterance_id: 2, tag_key: 'pain', quote: 'Every Monday I export all flagged listings to Excel', char_start: null, char_end: null, note: null, confidence: 0.95, origin: 'ai', status: 'accepted', created_at: '2026-08-12T12:00:00Z' },
    ],
    analyses: [{
      id: 1, conversation_id: 1, kind: 'conversation', model: 'gpt-4o', prompt_version: 'analyst-v1',
      input_scope: null,
      result: {
        summary: 'Brand manager spends half a Monday weekly.',
        top_pains: [{ pain: 'Manual Excel triage', evidence_highlight_ids: [1], severity: 'high' }],
        commitments: [],
        compliment_ratio: 0.1,
        mom_test_critique: { score: 8, good_questions: [], violations: [] },
        suggested_followups: [],
      },
      created_at: '2026-08-12T12:01:00Z',
    }],
  };
}
