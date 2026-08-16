import { useParams, Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api, Highlight, Utterance } from '../api';
import { useReviewQueue } from '../hooks/useReviewQueue';
import { NotesDrawer } from '../components/NotesDrawer';
import { AnalysisSidebar } from '../components/AnalysisSidebar';
import { HighlightPopover } from '../components/HighlightPopover';
import { TAG_META, tagEmoji } from '../constants';
import { useState, useCallback, useRef, useEffect } from 'react';

export function ConversationPage() {
  const { id } = useParams<{ id: string }>();
  const conversationId = Number(id);
  const queryClient = useQueryClient();

  const { data: convo, isLoading, error } = useQuery({
    queryKey: ['conversation', conversationId],
    queryFn: () => api.getConversation(conversationId),
    enabled: !!conversationId,
  });

  const updateHighlightMutation = useMutation({
    mutationFn: ({ highlightId, body }: { highlightId: number; body: { status?: string; tag_key?: string } }) =>
      api.updateHighlight(highlightId, body),
    onMutate: async ({ highlightId, body }) => {
      await queryClient.cancelQueries({ queryKey: ['conversation', conversationId] });
      queryClient.setQueryData(['conversation', conversationId], (old: typeof convo) => {
        if (!old) return old;
        return {
          ...old,
          highlights: old.highlights.map((h) =>
            h.id === highlightId ? { ...h, ...body } : h,
          ),
        };
      });
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['conversation', conversationId] });
    },
  });

  const createHighlightMutation = useMutation({
    mutationFn: (body: { utterance_id?: number; tag_key: string; quote: string }) =>
      api.createHighlight(conversationId, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['conversation', conversationId] });
    },
  });

  const suggestedHighlights = convo?.highlights.filter((h) => h.status === 'suggested') ?? [];
  const { focusNext, focusPrev, currentHighlight } = useReviewQueue(suggestedHighlights);

  const [popoverHighlight, setPopoverHighlight] = useState<Highlight | null>(null);
  const [popoverPos, setPopoverPos] = useState<{ top: number; left: number }>({ top: 0, left: 0 });
  const [flashUtteranceId, setFlashUtteranceId] = useState<number | null>(null);
  const transcriptRef = useRef<HTMLElement>(null);

  // Keyboard handling
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).tagName === 'TEXTAREA' || (e.target as HTMLElement).tagName === 'INPUT') return;
      if (e.key === 'j') {
        e.preventDefault();
        focusNext();
      } else if (e.key === 'k') {
        e.preventDefault();
        focusPrev();
      } else if (e.key === 'a' && currentHighlight) {
        e.preventDefault();
        updateHighlightMutation.mutate({ highlightId: currentHighlight.id, body: { status: 'accepted' } });
        focusNext();
      } else if (e.key === 'x' && currentHighlight) {
        e.preventDefault();
        updateHighlightMutation.mutate({ highlightId: currentHighlight.id, body: { status: 'rejected' } });
        focusNext();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [currentHighlight, focusNext, focusPrev, updateHighlightMutation]);

  // Scroll to focused highlight
  useEffect(() => {
    if (currentHighlight?.utterance_id) {
      const el = document.querySelector(`[data-utterance-id="${currentHighlight.utterance_id}"]`);
      el?.scrollIntoView({ block: 'center', behavior: 'smooth' });
    }
  }, [currentHighlight]);

  const handleChipClick = useCallback((highlight: Highlight, e: React.MouseEvent) => {
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    setPopoverHighlight(highlight);
    setPopoverPos({ top: rect.bottom + 8, left: Math.min(rect.left, window.innerWidth - 270) });
  }, []);

  const handleAcceptFromPopover = useCallback(() => {
    if (popoverHighlight) {
      updateHighlightMutation.mutate({ highlightId: popoverHighlight.id, body: { status: 'accepted' } });
      setPopoverHighlight(null);
    }
  }, [popoverHighlight, updateHighlightMutation]);

  const handleRejectFromPopover = useCallback(() => {
    if (popoverHighlight) {
      updateHighlightMutation.mutate({ highlightId: popoverHighlight.id, body: { status: 'rejected' } });
      setPopoverHighlight(null);
    }
  }, [popoverHighlight, updateHighlightMutation]);

  const handleRetagFromPopover = useCallback(
    (newTagKey: string) => {
      if (popoverHighlight) {
        updateHighlightMutation.mutate({ highlightId: popoverHighlight.id, body: { tag_key: newTagKey, status: 'accepted' } });
        setPopoverHighlight(null);
      }
    },
    [popoverHighlight, updateHighlightMutation],
  );

  const jumpToUtterance = useCallback((utteranceId: number) => {
    const el = document.querySelector(`[data-utterance-id="${utteranceId}"]`);
    if (el) {
      el.scrollIntoView({ block: 'center', behavior: 'smooth' });
      setFlashUtteranceId(utteranceId);
      setTimeout(() => setFlashUtteranceId(null), 1400);
    }
  }, []);

  // Text selection → manual highlight
  const handleTextSelect = useCallback(() => {
    const selection = window.getSelection();
    if (!selection || selection.isCollapsed) return;
    const text = selection.toString().trim();
    if (!text || text.length < 5) return;

    // Find the utterance element
    const anchorNode = selection.anchorNode;
    const uttEl = (anchorNode as HTMLElement)?.closest?.('[data-utterance-id]') ||
      (anchorNode?.parentElement as HTMLElement)?.closest?.('[data-utterance-id]');
    if (!uttEl) return;

    const utteranceId = Number(uttEl.getAttribute('data-utterance-id'));
    if (!utteranceId) return;

    // Show a simple prompt for tag selection (minimal affordance)
    const tagKey = window.prompt(`Add highlight for: "${text.slice(0, 60)}…"\n\nTag key (pain, workaround, money, commitment, etc.):`);
    if (tagKey && TAG_META[tagKey]) {
      createHighlightMutation.mutate({ utterance_id: utteranceId, tag_key: tagKey, quote: text });
      selection.removeAllRanges();
    }
  }, [createHighlightMutation]);

  if (isLoading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="w-4 h-4 border-2 border-hairline border-t-accent rounded-full animate-spin-slow" />
      </div>
    );
  }

  if (error || !convo) {
    return (
      <div className="flex-1 flex items-center justify-center text-crit">
        Failed to load conversation.
      </div>
    );
  }

  const analysis = convo.analyses.find((a) => a.kind === 'conversation');

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* Nav breadcrumb */}
      <div className="flex items-center gap-3.5 px-5 h-[42px] bg-surface border-b border-hairline flex-none">
        <Link to="/" className="text-muted hover:text-ink-2">
          Library
        </Link>
        <span className="text-muted">/</span>
        <span className="font-semibold truncate">{convo.title}</span>
        <div className="flex gap-1.5 ml-auto items-center">
          {convo.happened_at && (
            <span className="text-xs px-2 py-0.5 rounded-full bg-page border border-hairline text-ink-2">
              {new Date(convo.happened_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}
            </span>
          )}
          {convo.contacts[0] && (
            <span className="text-xs px-2 py-0.5 rounded-full bg-page border border-hairline text-ink-2">
              {convo.contacts[0].name}{convo.contacts[0].role ? ` · ${convo.contacts[0].role}` : ''}
            </span>
          )}
          {convo.meta && 'segment' in convo.meta && (
            <span className="text-xs px-2 py-0.5 rounded-full bg-page border border-hairline text-ink-2">
              {String(convo.meta.segment)}
            </span>
          )}
        </div>
      </div>

      <div className="flex-1 flex min-h-0">
        {/* Transcript */}
        <section ref={transcriptRef} className="flex-1 overflow-y-auto px-8 py-6 pb-32" onMouseUp={handleTextSelect}>
          {/* Review banner */}
          {suggestedHighlights.length > 0 && (
            <div className="sticky top-0 z-10 flex gap-2.5 items-center bg-accent-soft border border-[#bcd7f5] rounded-xl px-3.5 py-2 mb-4 text-[13px]">
              <b>Review mode</b> — {suggestedHighlights.filter((h) => h.status === 'suggested').length} suggestions left ·
              <span>
                <kbd className="bg-surface border border-hairline border-b-2 rounded px-1.5 font-mono text-xs">j</kbd>/
                <kbd className="bg-surface border border-hairline border-b-2 rounded px-1.5 font-mono text-xs">k</kbd> next/prev ·{' '}
                <kbd className="bg-surface border border-hairline border-b-2 rounded px-1.5 font-mono text-xs">a</kbd> accept ·{' '}
                <kbd className="bg-surface border border-hairline border-b-2 rounded px-1.5 font-mono text-xs">x</kbd> reject
              </span>
            </div>
          )}

          {/* Utterances */}
          {convo.utterances.map((utt) => {
            const uttHighlights = convo.highlights.filter(
              (h) => h.utterance_id === utt.id && h.status !== 'rejected',
            );
            const hasHighlights = uttHighlights.length > 0;
            const isFocused = currentHighlight?.utterance_id === utt.id;
            const isFlashing = flashUtteranceId === utt.id;

            return (
              <div
                key={utt.id}
                data-utterance-id={utt.id}
                className={`flex gap-3 px-2.5 py-1.5 rounded-xl max-w-[760px] transition-all ${
                  hasHighlights ? 'bg-[#fdf9ee]' : ''
                } ${isFocused ? 'outline outline-2 outline-accent -outline-offset-2' : ''} ${
                  isFlashing ? 'ring-2 ring-accent ring-offset-2' : ''
                }`}
              >
                <div
                  className={`w-16 flex-none text-xs font-bold pt-0.5 ${
                    utt.speaker_side === 'us' ? 'text-accent' : 'text-ink-2'
                  }`}
                >
                  {utt.speaker_label}
                </div>
                <div className="flex-1">
                  <p className={utt.speaker_side === 'us' ? 'text-ink-2' : 'text-ink'}>
                    {renderHighlightedText(utt, uttHighlights)}
                  </p>
                  {uttHighlights.length > 0 && (
                    <div className="flex gap-1.5 mt-1.5 flex-wrap">
                      {uttHighlights.map((h) => (
                        <button
                          key={h.id}
                          onClick={(e) => handleChipClick(h, e)}
                          className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full cursor-pointer ${
                            h.status === 'suggested'
                              ? 'border border-dashed border-[#c9a227] bg-[#fdf6e0] text-ink-2'
                              : 'border border-[#9ec5f4] bg-accent-soft text-[#1c5cab] font-semibold'
                          }`}
                        >
                          {tagEmoji(h.tag_key)} {TAG_META[h.tag_key]?.name || h.tag_key}
                          {h.status === 'suggested' && h.confidence != null && (
                            <span className="text-muted font-normal ml-1">{h.confidence.toFixed(2)}</span>
                          )}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            );
          })}

          <p className="text-muted text-xs mt-4">
            Tip: select any text in an utterance to add a manual highlight.
          </p>
        </section>

        {/* Analysis sidebar */}
        <AnalysisSidebar analysis={analysis ?? null} highlights={convo.highlights} onJumpToUtterance={jumpToUtterance} />
      </div>

      {/* Popover */}
      {popoverHighlight && (
        <HighlightPopover
          highlight={popoverHighlight}
          position={popoverPos}
          onAccept={handleAcceptFromPopover}
          onReject={handleRejectFromPopover}
          onRetag={handleRetagFromPopover}
          onClose={() => setPopoverHighlight(null)}
        />
      )}

      {/* Notes drawer */}
      <NotesDrawer conversationId={conversationId} />
    </div>
  );
}

function renderHighlightedText(utterance: Utterance, highlights: Highlight[]): React.ReactNode {
  // Simple approach: if a highlight has a quote, mark it in the text
  let text = utterance.text;
  const parts: React.ReactNode[] = [];
  let lastIdx = 0;

  // Sort highlights by their quote position in text
  const sortedHls = highlights
    .filter((h) => h.quote)
    .map((h) => {
      const idx = text.indexOf(h.quote);
      return { ...h, startIdx: idx };
    })
    .filter((h) => h.startIdx >= 0)
    .sort((a, b) => a.startIdx - b.startIdx);

  for (const hl of sortedHls) {
    if (hl.startIdx < lastIdx) continue; // overlapping
    if (hl.startIdx > lastIdx) {
      parts.push(<span key={`t-${lastIdx}`}>{text.slice(lastIdx, hl.startIdx)}</span>);
    }
    parts.push(
      <mark key={`hl-${hl.id}`} className="bg-[#fbe9b8] rounded px-0.5">
        {hl.quote}
      </mark>,
    );
    lastIdx = hl.startIdx + hl.quote.length;
  }
  if (lastIdx < text.length) {
    parts.push(<span key={`t-${lastIdx}`}>{text.slice(lastIdx)}</span>);
  }

  return parts.length > 0 ? <>{parts}</> : text;
}
