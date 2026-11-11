/** v0.5 U6: one review bar, inline Accept/Reject on each suggested tag, and no empty gap. */
import { describe, expect, test } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { Route, Routes } from 'react-router-dom';
import { server } from '../test/mocks/server';
import { renderWithProviders } from '../test/render';
import { ConversationPage } from '../pages/ConversationPage';

const utt = (id: number, text: string, side = 'them') => ({ id, conversation_id: 1, idx: id, speaker_label: side === 'us' ? 'Rep' : 'Pat', speaker_side: side, text, start_ms: null });
const hl = (id: number, utterance_id: number, tag_key: string, status: string, confidence: number | null) => ({
  id, conversation_id: 1, utterance_id, tag_key, quote: `quote ${id}`, char_start: null, char_end: null, note: null,
  confidence, origin: 'ai', status, created_at: '2026-11-02T09:00:00Z',
});

function setup(highlights = [
  hl(1, 1, 'pain', 'suggested', 0.95),
  hl(2, 2, 'workaround', 'suggested', 0.92),
  hl(3, 3, 'money', 'suggested', 0.6),
  hl(4, 4, 'pain', 'accepted', 1.0),
]) {
  const patches: Array<{ id: string; body: Record<string, unknown> }> = [];
  const bulks: Array<Record<string, unknown>> = [];
  server.use(
    http.get('/api/conversations/1', () => HttpResponse.json({
      id: 1, title: 'Call', happened_at: '2026-11-02T09:00:00Z', status: 'ready', source: 'upload', interviewer: 'Rep',
      company: { id: 1, name: 'Acme' }, contacts: [], meta: null, created_at: '2026-11-02T09:00:00Z',
      utterances: [utt(1, 'We export to Excel every Monday by hand.'), utt(2, 'It takes two hours and nobody trusts it.'),
        utt(3, 'Our budget for this is five thousand euros.'), utt(4, 'It is a real problem for the whole team here.')],
      highlights, analyses: [],
    })),
    http.patch('/api/highlights/:id', async ({ request, params }) => {
      const body = (await request.json()) as Record<string, unknown>;
      patches.push({ id: String(params.id), body });
      return HttpResponse.json({ ...highlights.find((h) => h.id === Number(params.id)), ...body });
    }),
    http.post('/api/highlights/bulk-accept', async ({ request }) => {
      bulks.push((await request.json()) as Record<string, unknown>);
      return HttpResponse.json({ accepted_count: 2, accepted_ids: [1, 2] });
    }),
  );
  renderWithProviders(<Routes><Route path="/conversations/:id" element={<ConversationPage />} /></Routes>, { route: '/conversations/1' });
  return { patches, bulks };
}

describe('Review bar', () => {
  test('one bar says how many are left, with a progress bar and the keyboard hint', async () => {
    setup();
    const bar = await screen.findByRole('region', { name: /review ai tags/i });
    expect(within(bar).getByText(/review ai tags · 3 left/i)).toBeInTheDocument();
    const progress = within(bar).getByRole('progressbar', { name: /review progress/i });
    expect(progress).toHaveAttribute('aria-valuenow', '1');     // 1 of 4 reviewed
    expect(progress).toHaveAttribute('aria-valuemax', '4');
    for (const key of ['j', 'k', 'a', 'x']) expect(within(bar).getByText(key)).toBeInTheDocument();
  });

  test('"Accept all ≥ 0.9" shows its count and confirms before bulk-accepting', async () => {
    const { bulks } = setup();
    const user = userEvent.setup();
    const confirm = window.confirm;
    window.confirm = () => true;
    try {
      const bar = await screen.findByRole('region', { name: /review ai tags/i });
      await user.click(within(bar).getByRole('button', { name: /accept all ≥ 0\.9 \(2\)/i }));
      await waitFor(() => expect(bulks).toHaveLength(1));
      expect(bulks[0]).toEqual({ min_confidence: 0.9, conversation_id: 1 });
    } finally {
      window.confirm = confirm;
    }
  });

  test('"Accept all ≥ 0.9" is disabled when nothing qualifies', async () => {
    setup([hl(3, 3, 'money', 'suggested', 0.6)]);
    const bar = await screen.findByRole('region', { name: /review ai tags/i });
    expect(within(bar).getByRole('button', { name: /accept all ≥ 0\.9 \(0\)/i })).toBeDisabled();
  });

  test('the bar disappears when nothing is left to review', async () => {
    setup([hl(4, 4, 'pain', 'accepted', 1.0)]);
    await screen.findByText(/real problem for the whole team/);
    expect(screen.queryByRole('region', { name: /review ai tags/i })).not.toBeInTheDocument();
  });

  test('the bar stays pinned while the transcript scrolls', async () => {
    setup();
    const bar = await screen.findByRole('region', { name: /review ai tags/i });
    expect(bar.className).toMatch(/sticky/);
  });
});

describe('Inline Accept / Reject on each suggested tag', () => {
  test('a suggested tag shows Accept and Reject right next to it', async () => {
    setup();
    await screen.findByText(/export to Excel/);
    expect(screen.getByRole('button', { name: /accept pain/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /reject pain/i })).toBeInTheDocument();
  });

  test('Accept sends the status change and the tag turns solid', async () => {
    const { patches } = setup();
    const user = userEvent.setup();
    const accept = await screen.findByRole('button', { name: /accept workaround/i });
    await user.click(accept);
    await waitFor(() => expect(patches).toContainEqual({ id: '2', body: { status: 'accepted' } }));
    await waitFor(() => expect(screen.queryByRole('button', { name: /accept workaround/i })).not.toBeInTheDocument());
    const chip = screen.getByText(/Workaround/i).closest('[data-status]') as HTMLElement;
    expect(chip.getAttribute('data-status')).toBe('accepted');
    expect(chip.className).not.toMatch(/border-dashed/);
  });

  test('Reject sends the status change and removes the tag', async () => {
    const { patches } = setup();
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: /reject money/i }));
    await waitFor(() => expect(patches).toContainEqual({ id: '3', body: { status: 'rejected' } }));
    await waitFor(() => expect(screen.queryByRole('button', { name: /reject money/i })).not.toBeInTheDocument());
  });

  test('the progress and the left-count move as tags are reviewed', async () => {
    setup();
    const user = userEvent.setup();
    const bar = await screen.findByRole('region', { name: /review ai tags/i });
    await user.click(screen.getByRole('button', { name: /accept pain/i }));
    await waitFor(() => expect(within(bar).getByText(/review ai tags · 2 left/i)).toBeInTheDocument());
    expect(within(bar).getByRole('progressbar', { name: /review progress/i })).toHaveAttribute('aria-valuenow', '2');
  });

  test('accepted tags have no Accept/Reject buttons', async () => {
    setup([hl(4, 4, 'pain', 'accepted', 1.0)]);
    await screen.findByText(/real problem for the whole team/);
    expect(screen.queryByRole('button', { name: /accept pain/i })).not.toBeInTheDocument();
  });
});

describe('Layout', () => {
  test('the transcript fills the space but keeps lines readable (about 80 characters)', async () => {
    setup();
    await screen.findByText(/export to Excel/);
    const line = document.querySelector('[data-utterance-id="1"]') as HTMLElement;
    // The row spans the transcript (so its highlight band meets the analysis panel); only the text is capped.
    expect(line.className).not.toMatch(/max-w-/);
    expect(line.querySelector('[data-raw-text]')!.className).toMatch(/max-w-\[80ch\]/);
    // The transcript itself is the flexible column, so no gap opens beside the analysis panel.
    const transcript = line.closest('section') as HTMLElement;
    expect(transcript.className).toMatch(/flex-1/);
  });
});
