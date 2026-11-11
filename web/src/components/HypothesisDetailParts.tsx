/**
 * Pieces of the hypothesis detail panel: inline edit, validation questions,
 * band history, and the "Add evidence" picker.
 */
import { useState, FormEvent } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api, HypothesisDetail, HypothesisBandEvent } from '../api';
import { formatDate } from '../utils/format';

const BAND_LABEL: Record<string, string> = {
  grounded: 'Grounded',
  contested: 'Contested',
  candidate: 'Candidate',
  hunch: 'Hunch',
  refuted: 'Refuted',
};

function shortDate(iso: string): string {
  return formatDate(iso);
}

function useInvalidateHypothesis(id: number) {
  const queryClient = useQueryClient();
  return () => {
    queryClient.invalidateQueries({ queryKey: ['hypotheses'] });
    queryClient.invalidateQueries({ queryKey: ['hypothesis', id] });
    queryClient.invalidateQueries({ queryKey: ['hypothesis-history', id] });
    queryClient.invalidateQueries({ queryKey: ['hypothesis-segments'] });
  };
}

// ─── Inline edit (statement + segment) ───

export function InlineEdit({
  id,
  statement,
  segment,
  hasEvidenceLinks,
}: {
  id: number;
  statement: string;
  segment: string | null;
  hasEvidenceLinks: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [draftStatement, setDraftStatement] = useState(statement);
  const [draftSegment, setDraftSegment] = useState(segment ?? '');
  const [error, setError] = useState('');
  const invalidate = useInvalidateHypothesis(id);

  const save = useMutation({
    mutationFn: () => {
      const body: { statement?: string; segment?: string } = {};
      if (!hasEvidenceLinks && draftStatement.trim() !== statement) {
        body.statement = draftStatement.trim();
      }
      if (draftSegment.trim() !== (segment ?? '')) body.segment = draftSegment.trim();
      return api.updateHypothesis(id, body);
    },
    onSuccess: () => {
      setEditing(false);
      setError('');
      invalidate();
    },
    onError: (e: Error) => setError(e.message || 'Could not save changes.'),
  });

  if (!editing) {
    return (
      <button
        type="button"
        onClick={() => {
          setDraftStatement(statement);
          setDraftSegment(segment ?? '');
          setEditing(true);
        }}
        className="text-xs font-semibold text-accent hover:underline"
      >
        Edit
      </button>
    );
  }

  const tooShort = !hasEvidenceLinks && draftStatement.trim().length < 15;
  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!tooShort) save.mutate();
  };

  return (
    <form onSubmit={onSubmit} className="w-full flex flex-col gap-2 mt-2" aria-label="Edit hypothesis">
      <label className="flex flex-col gap-1 text-xs font-semibold text-muted">
        Belief
        <input
          type="text"
          value={draftStatement}
          disabled={hasEvidenceLinks}
          onChange={(e) => setDraftStatement(e.target.value)}
          className="h-9 px-3 border border-hairline rounded-lg bg-surface text-sm font-normal text-ink disabled:bg-sub disabled:text-muted"
        />
      </label>
      {hasEvidenceLinks && (
        <p className="text-xs text-muted">
          The belief can’t be reworded once quotes are linked — archive it and add a new one instead.
        </p>
      )}
      <label className="flex flex-col gap-1 text-xs font-semibold text-muted">
        Segment
        <input
          type="text"
          value={draftSegment}
          onChange={(e) => setDraftSegment(e.target.value)}
          className="h-9 px-3 border border-hairline rounded-lg bg-surface text-sm font-normal text-ink"
        />
      </label>
      {error && <p role="alert" className="text-xs text-red-600">{error}</p>}
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={tooShort || save.isPending}
          className="h-8 px-3 rounded-lg text-xs font-semibold bg-accent text-white disabled:opacity-50"
        >
          Save changes
        </button>
        <button
          type="button"
          onClick={() => setEditing(false)}
          className="h-8 px-3 rounded-lg text-xs font-semibold border border-hairline text-ink-2"
        >
          Cancel edit
        </button>
      </div>
    </form>
  );
}

// ─── Validation questions ───

export function QuestionsList({
  hypothesisId,
  questions,
}: {
  hypothesisId: number;
  questions: NonNullable<HypothesisDetail['questions']>;
}) {
  const invalidate = useInvalidateHypothesis(hypothesisId);
  const toggle = useMutation({
    mutationFn: ({ qid, asked }: { qid: number; asked: boolean }) =>
      api.setHypothesisQuestionAsked(hypothesisId, qid, asked),
    onSuccess: invalidate,
  });
  if (questions.length === 0) return null;
  return (
    <section aria-label="Validation questions" className="mt-4 border-t border-hairline pt-3">
      <h3 className="text-xs font-semibold text-muted mb-2">Questions to ask next</h3>
      <ul className="space-y-1.5">
        {questions.map((q) => (
          <li key={q.id} className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              className="mt-1"
              aria-label={`Mark asked: ${q.text}`}
              checked={q.asked_at != null}
              onChange={(e) => toggle.mutate({ qid: q.id, asked: e.target.checked })}
            />
            <span className={q.asked_at ? 'text-muted line-through' : 'text-ink-2'}>{q.text}</span>
            {q.asked_at && <span className="text-xs text-muted">asked {shortDate(q.asked_at)}</span>}
          </li>
        ))}
      </ul>
    </section>
  );
}

// ─── Band history ───

export function BandHistory({ hypothesisId }: { hypothesisId: number }) {
  const { data } = useQuery({
    queryKey: ['hypothesis-history', hypothesisId],
    queryFn: () => api.hypothesisHistory(hypothesisId),
  });
  const items: HypothesisBandEvent[] = data?.items ?? [];
  if (items.length === 0) return null;
  return (
    <section aria-label="Band history" className="mt-4 border-t border-hairline pt-3">
      <h3 className="text-xs font-semibold text-muted mb-2">Why it sits here</h3>
      <ol className="space-y-1.5">
        {items.map((e) => (
          <li key={e.id} className="text-sm text-ink-2">
            <span className="text-xs text-muted tabular-nums mr-2">{shortDate(e.created_at)}</span>
            {e.from_band == null ? (
              <>Added as <b>{BAND_LABEL[e.to_band] ?? e.to_band}</b></>
            ) : (
              <>
                <b>{BAND_LABEL[e.from_band] ?? e.from_band}</b> → <b>{BAND_LABEL[e.to_band] ?? e.to_band}</b>
              </>
            )}
            {e.cause_quote && (
              <span className="block text-xs text-muted italic">
                {e.cause_stance === 'contradicts' ? 'contradicted by' : 'supported by'} “{e.cause_quote}”
              </span>
            )}
          </li>
        ))}
      </ol>
    </section>
  );
}

// ─── Add evidence ───

export function AddEvidence({
  hypothesisId,
  linkedHighlightIds,
}: {
  hypothesisId: number;
  linkedHighlightIds: Set<number>;
}) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState('');
  const [error, setError] = useState('');
  const invalidate = useInvalidateHypothesis(hypothesisId);
  const term = q.trim();

  const { data, isFetching } = useQuery({
    queryKey: ['hypothesis-evidence-search', term],
    queryFn: () => api.listHighlights({ q: term, limit: 8 }),
    enabled: open && term.length >= 3,
  });
  const results = (data?.items ?? []).filter((h) => !linkedHighlightIds.has(h.id));

  const add = useMutation({
    mutationFn: (body: { highlight_id: number; stance: 'supports' | 'contradicts' }) =>
      api.addHypothesisLink(hypothesisId, { ...body, confirm: true }),
    onSuccess: () => {
      setError('');
      invalidate();
    },
    onError: (e: Error) => setError(e.message || 'Could not add that quote.'),
  });

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="mt-4 text-sm font-semibold text-accent hover:underline"
      >
        Add evidence
      </button>
    );
  }

  return (
    <section aria-label="Add evidence" className="mt-4 border-t border-hairline pt-3">
      <div className="flex items-center gap-2 mb-2">
        <h3 className="text-xs font-semibold text-muted">Add evidence</h3>
        <button type="button" onClick={() => setOpen(false)} className="ml-auto text-xs text-muted hover:text-ink">
          Close search
        </button>
      </div>
      <input
        type="search"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="Search what customers said…"
        aria-label="Search quotes"
        className="w-full h-9 px-3 border border-hairline rounded-lg bg-surface text-sm"
      />
      <p className="mt-1 text-xs text-muted">Linking a quote counts it as confirmed evidence.</p>
      {error && <p role="alert" className="mt-1 text-xs text-red-600">{error}</p>}
      {term.length >= 3 && !isFetching && results.length === 0 && (
        <p className="mt-2 text-sm text-muted">No matching quotes.</p>
      )}
      <ul className="mt-2 space-y-2">
        {results.map((h) => (
          <li key={h.id} className="flex items-start gap-2 text-sm border border-hairline rounded-lg p-2">
            <div className="flex-1 min-w-0">
              <span className="italic">“{h.quote}”</span>
              <span className="block text-xs text-muted">
                {[h.company_name, h.contact_names?.[0]].filter(Boolean).join(' · ') || 'Unknown source'}
              </span>
            </div>
            <div className="flex gap-1.5 shrink-0">
              <button
                type="button"
                disabled={add.isPending}
                onClick={() => add.mutate({ highlight_id: h.id, stance: 'supports' })}
                aria-label={`Link as supports: ${h.quote}`}
                className="text-xs font-semibold px-2 py-1 rounded bg-green-100 text-green-800 hover:bg-green-200"
              >
                Supports
              </button>
              <button
                type="button"
                disabled={add.isPending}
                onClick={() => add.mutate({ highlight_id: h.id, stance: 'contradicts' })}
                aria-label={`Link as contradicts: ${h.quote}`}
                className="text-xs font-semibold px-2 py-1 rounded bg-red-100 text-red-800 hover:bg-red-200"
              >
                Contradicts
              </button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
