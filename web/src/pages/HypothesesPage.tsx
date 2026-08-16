/**
 * T28 — Hypothesis Board Page
 *
 * Accessible responsive board for tracking hypotheses with:
 * - Status chips, evidence meter with hatched suggested extension
 * - Expandable grouped evidence with source utterance hash links
 * - Optimistic inline accept/reject for suggested links
 * - Confirmation before supported/refuted status transitions
 * - Composer with >=15 trimmed chars validation
 * - Loading/empty/error states and keyboard semantics
 */
import { useState, useRef, FormEvent, KeyboardEvent } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  api,
  HypothesisListItem,
  HypothesisDetail,
  HypothesisEvidenceLink,
} from '../api';

// ─── Status chip component ───

function StatusChip({ status }: { status: string }) {
  const base = 'inline-block text-xs font-bold px-2.5 py-0.5 rounded-full tracking-wide uppercase';
  let color = '';
  switch (status) {
    case 'open':
      color = 'bg-accent-soft text-accent';
      break;
    case 'supported':
      color = 'bg-green-100 text-green-800';
      break;
    case 'refuted':
      color = 'bg-red-100 text-red-800';
      break;
    case 'parked':
      color = 'bg-gray-100 text-gray-600';
      break;
    default:
      color = 'bg-gray-100 text-gray-600';
  }
  return <span className={`${base} ${color}`}>{status.toUpperCase()}</span>;
}

// ─── Evidence Meter ───

function EvidenceMeter({ rollup }: { rollup: HypothesisListItem['rollup'] }) {
  const confirmedSupport = rollup.supports.confirmed;
  const confirmedContradict = rollup.contradicts.confirmed;
  const suggestedSupport = rollup.supports.suggested;
  const total = confirmedSupport + confirmedContradict + suggestedSupport + rollup.contradicts.suggested;

  // Calculate meter fill percentages
  const supportPct = total > 0 ? (confirmedSupport / total) * 100 : 0;
  const suggestedPct = total > 0 ? (suggestedSupport / total) * 100 : 0;

  return (
    <div
      role="meter"
      aria-label="Evidence meter"
      aria-valuenow={confirmedSupport}
      aria-valuemin={0}
      aria-valuemax={total || 1}
      className="flex-1 h-2 rounded-full bg-blue-100 overflow-hidden flex"
    >
      <div
        className="h-full bg-accent"
        style={{ width: `${supportPct}%` }}
      />
      <div
        data-testid="meter-suggested"
        aria-label="suggested evidence"
        className="h-full opacity-50"
        style={{
          width: `${suggestedPct}%`,
          background: 'repeating-linear-gradient(45deg, var(--color-accent, #2a78d6) 0 3px, transparent 3px 6px)',
        }}
      />
    </div>
  );
}

// ─── Evidence Stats Summary ───

function EvidenceStats({ rollup, verdict_hint, decided_at, status }: {
  rollup: HypothesisListItem['rollup'];
  verdict_hint: string | null;
  decided_at: string | null;
  status: string;
}) {
  const suggestedTotal = rollup.supports.suggested + rollup.contradicts.suggested;

  return (
    <div className="flex items-center gap-3 mt-3 text-xs text-gray-500 flex-wrap">
      <span>
        <b className="text-gray-700">{rollup.supports.confirmed} support</b>
        {rollup.companies_supporting > 0 && (
          <span> ({rollup.companies_supporting} companies)</span>
        )}
        {' · '}
        <b className="text-gray-700">{rollup.contradicts.confirmed} contradicts</b>
        {rollup.companies_contradicting > 0 && (
          <span> ({rollup.companies_contradicting} companies)</span>
        )}
        {suggestedTotal > 0 && ` · ${suggestedTotal} suggested`}
      </span>
      {verdict_hint && status === 'open' && (
        <span className="text-green-700 font-semibold">
          ↗ leaning supported
        </span>
      )}
      {status === 'refuted' && decided_at && (
        <span className="text-red-700 font-semibold">
          ↘ refuted {formatShortDate(decided_at)}
        </span>
      )}
      {status === 'supported' && decided_at && (
        <span className="text-green-700 font-semibold">
          ↗ supported {formatShortDate(decided_at)}
        </span>
      )}
    </div>
  );
}

function formatShortDate(dateStr: string): string {
  const d = new Date(dateStr);
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

// ─── Evidence Link Item ───

function EvidenceLinkItem({
  link,
  onAccept,
  onReject,
}: {
  link: HypothesisEvidenceLink;
  onAccept: () => void;
  onReject: () => void;
}) {
  const isSuggested = link.status === 'suggested';

  return (
    <div
      data-status={link.status}
      className={`flex gap-3 items-baseline text-sm p-2.5 rounded-lg mb-1.5 ${
        isSuggested
          ? 'suggested border-2 border-dashed border-yellow-500 bg-yellow-50'
          : 'bg-gray-50'
      }`}
    >
      <blockquote className="flex-1 text-gray-600 italic">
        &ldquo;{link.quote}&rdquo;
      </blockquote>
      <div className="flex items-center gap-2 shrink-0">
        {isSuggested && (
          <>
            <button
              type="button"
              onClick={onAccept}
              className="text-xs font-bold px-2 py-0.5 rounded bg-green-100 text-green-800 hover:bg-green-200"
              aria-label="Accept"
            >
              ✓ accept
            </button>
            <button
              type="button"
              onClick={onReject}
              className="text-xs font-bold px-2 py-0.5 rounded bg-red-100 text-red-800 hover:bg-red-200"
              aria-label="Reject"
            >
              ✕
            </button>
          </>
        )}
        <a
          href={`/conversations/${link.conversation_id}#utterance-${link.utterance_id}`}
          className="text-xs text-accent whitespace-nowrap hover:underline"
        >
          {link.company_name} ↗
        </a>
      </div>
    </div>
  );
}

// ─── Expanded Evidence Section ───

function EvidenceSection({
  evidence,
  hypothesisStatus,
  onStatusChange,
}: {
  evidence: HypothesisDetail['evidence'];
  hypothesisStatus: string;
  onStatusChange: (status: string) => void;
}) {
  const queryClient = useQueryClient();
  const [confirmAction, setConfirmAction] = useState<string | null>(null);
  const [optimisticUpdates, setOptimisticUpdates] = useState<Record<number, string>>({});

  const linkMutation = useMutation({
    mutationFn: ({ linkId, status }: { linkId: number; status: 'confirmed' | 'rejected' }) =>
      api.patchHypothesisLink(linkId, { status }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hypotheses'] });
      queryClient.invalidateQueries({ queryKey: ['hypothesis'] });
    },
  });

  const handleAccept = (linkId: number) => {
    setOptimisticUpdates((prev) => ({ ...prev, [linkId]: 'confirmed' }));
    linkMutation.mutate({ linkId, status: 'confirmed' });
  };

  const handleReject = (linkId: number) => {
    setOptimisticUpdates((prev) => ({ ...prev, [linkId]: 'rejected' }));
    linkMutation.mutate({ linkId, status: 'rejected' });
  };

  const handleConfirmAction = () => {
    if (confirmAction) {
      onStatusChange(confirmAction);
      setConfirmAction(null);
    }
  };

  // Filter evidence based on optimistic updates
  const filterLinks = (links: HypothesisEvidenceLink[]) =>
    links
      .filter((link) => optimisticUpdates[link.link_id] !== 'rejected')
      .map((link) => ({
        ...link,
        status: optimisticUpdates[link.link_id] || link.status,
      }));

  const supportsFiltered = filterLinks(evidence.supports);
  const contradictsFiltered = filterLinks(evidence.contradicts);

  return (
    <div role="region" aria-label="Evidence detail" className="mt-4 border-t border-gray-200 pt-4">
      {/* Evidence content — hidden during confirmation to avoid text collisions */}
      {confirmAction === null && (
        <>
          {/* Supports section */}
          <h4 className="text-xs font-bold uppercase tracking-wider text-green-800 mb-2">
            Supports · confirmed
          </h4>
          {supportsFiltered.map((link) => (
            <EvidenceLinkItem
              key={link.link_id}
              link={link}
              onAccept={() => handleAccept(link.link_id)}
              onReject={() => handleReject(link.link_id)}
            />
          ))}

          {/* Contradicts section */}
          {contradictsFiltered.length > 0 && (
            <>
              <h4 className="text-xs font-bold uppercase tracking-wider text-red-800 mt-4 mb-2">
                Contradicts
              </h4>
              {contradictsFiltered.map((link) => (
                <EvidenceLinkItem
                  key={link.link_id}
                  link={link}
                  onAccept={() => handleAccept(link.link_id)}
                  onReject={() => handleReject(link.link_id)}
                />
              ))}
            </>
          )}
        </>
      )}

      {/* Decision actions for open hypotheses */}
      {hypothesisStatus === 'open' && (
        <div className="flex gap-2 mt-4">
          {confirmAction === null ? (
            <>
              <button
                type="button"
                onClick={() => setConfirmAction('supported')}
                className="px-3 py-1.5 border border-gray-200 rounded-lg text-sm font-semibold text-green-700 hover:bg-green-50"
              >
                Mark supported
              </button>
              <button
                type="button"
                onClick={() => setConfirmAction('refuted')}
                className="px-3 py-1.5 border border-gray-200 rounded-lg text-sm font-semibold text-red-700 hover:bg-red-50"
              >
                Mark refuted
              </button>
              <button
                type="button"
                onClick={() => onStatusChange('parked')}
                className="px-3 py-1.5 border border-gray-200 rounded-lg text-sm font-semibold text-gray-600 hover:bg-gray-50"
              >
                Park
              </button>
            </>
          ) : (
            <div className="flex items-center gap-3">
              <span className="text-sm text-gray-600">
                Are you sure you want to mark this hypothesis as {confirmAction}?
              </span>
              <button
                type="button"
                onClick={handleConfirmAction}
                className="px-3 py-1.5 rounded-lg text-sm font-semibold bg-accent text-white hover:bg-accent/90"
              >
                Yes
              </button>
              <button
                type="button"
                onClick={() => setConfirmAction(null)}
                className="px-3 py-1.5 rounded-lg text-sm font-semibold text-gray-600 hover:bg-gray-50"
              >
                Cancel
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Hypothesis Card ───

function HypothesisCard({
  hypothesis,
  isExpanded,
  onToggle,
}: {
  hypothesis: HypothesisListItem;
  isExpanded: boolean;
  onToggle: () => void;
}) {
  const queryClient = useQueryClient();

  // Fetch detail when expanded
  const { data: detail } = useQuery({
    queryKey: ['hypothesis', hypothesis.id],
    queryFn: () => api.getHypothesis(hypothesis.id),
    enabled: isExpanded,
  });

  const statusMutation = useMutation({
    mutationFn: (newStatus: string) => api.updateHypothesis(hypothesis.id, { status: newStatus }),
    onSuccess: (data) => {
      // Update the hypothesis in the list cache with the response data
      queryClient.setQueryData<HypothesisListItem[]>(
        ['hypotheses'],
        (old) =>
          (old || []).map((h) =>
            h.id === hypothesis.id
              ? { ...h, status: data.status, decided_at: data.decided_at }
              : h,
          ),
      );
    },
  });

  const suggestedCount = hypothesis.rollup.supports.suggested + hypothesis.rollup.contradicts.suggested;

  return (
    <article data-testid="hypothesis-card" className="bg-white border border-gray-200 rounded-xl p-4 mb-3.5">
      {/* Card header — clickable for expansion */}
      <div
        role="button"
        tabIndex={0}
        onClick={onToggle}
        onKeyDown={(e: KeyboardEvent<HTMLDivElement>) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            onToggle();
          }
        }}
        aria-expanded={isExpanded}
        className="flex items-start gap-3 cursor-pointer"
      >
        <div className="flex-1">
          <span className="text-sm font-semibold">{hypothesis.statement}</span>
        </div>
        {suggestedCount > 0 && (
          <span className="text-xs text-yellow-800 bg-yellow-50 border border-yellow-200 px-2 py-0.5 rounded-full whitespace-nowrap">
            {suggestedCount} to review
          </span>
        )}
        <StatusChip status={hypothesis.status} />
      </div>

      {/* Meter row */}
      <div className="flex items-center gap-3 mt-3">
        <EvidenceMeter rollup={hypothesis.rollup} />
      </div>

      {!isExpanded && (
        <EvidenceStats
          rollup={hypothesis.rollup}
          verdict_hint={hypothesis.verdict_hint}
          decided_at={hypothesis.decided_at}
          status={hypothesis.status}
        />
      )}

      {/* Expanded evidence detail */}
      {isExpanded && detail && (
        <EvidenceSection
          evidence={detail.evidence}
          hypothesisStatus={hypothesis.status}
          onStatusChange={(status) => statusMutation.mutate(status)}
        />
      )}
    </article>
  );
}

// ─── Composer ───

function HypothesisComposer() {
  const [statement, setStatement] = useState('');
  const [validationError, setValidationError] = useState('');
  const [submitError, setSubmitError] = useState(false);
  const queryClient = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);

  const createMutation = useMutation({
    mutationFn: (body: { statement: string }) => api.createHypothesis(body),
    onMutate: async (body) => {
      // Cancel outgoing fetches
      await queryClient.cancelQueries({ queryKey: ['hypotheses'] });

      // Snapshot previous value
      const previous = queryClient.getQueryData<HypothesisListItem[]>(['hypotheses']);

      // Optimistically add
      const optimistic: HypothesisListItem = {
        id: -Date.now(),
        statement: body.statement,
        segment: null,
        status: 'open',
        created_by: null,
        created_at: new Date().toISOString(),
        decided_at: null,
        rollup: {
          supports: { confirmed: 0, suggested: 0 },
          contradicts: { confirmed: 0, suggested: 0 },
          companies_supporting: 0,
          companies_contradicting: 0,
          last_evidence_at: null,
        },
        verdict_hint: null,
      };

      queryClient.setQueryData<HypothesisListItem[]>(
        ['hypotheses'],
        (old) => [optimistic, ...(old || [])],
      );

      // Clear input immediately
      setStatement('');
      setValidationError('');
      setSubmitError(false);

      return { previous, optimisticId: optimistic.id };
    },
    onError: (_err, _body, context) => {
      // Roll back optimistic update
      if (context?.previous) {
        queryClient.setQueryData(['hypotheses'], context.previous);
      }
      setSubmitError(true);
    },
    onSuccess: (data, _body, context) => {
      // Replace the optimistic entry with the real server response
      queryClient.setQueryData<HypothesisListItem[]>(
        ['hypotheses'],
        (old) =>
          (old || []).map((h) => (h.id === context?.optimisticId ? data : h)),
      );
    },
  });

  const handleSubmit = (e?: FormEvent) => {
    e?.preventDefault();
    const trimmed = statement.trim();
    if (trimmed.length < 15) {
      setValidationError('Statement must be at least 15 characters');
      return;
    }
    setValidationError('');
    createMutation.mutate({ statement: trimmed });
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleSubmit();
    }
  };

  const trimmedLength = statement.trim().length;
  const isDisabled = trimmedLength === 0;

  return (
    <div className="mb-5">
      <form onSubmit={handleSubmit} className="flex gap-2">
        <input
          ref={inputRef}
          type="text"
          value={statement}
          onChange={(e) => {
            setStatement(e.target.value);
            if (validationError) setValidationError('');
            if (submitError) setSubmitError(false);
          }}
          onKeyDown={handleKeyDown}
          placeholder={'State a falsifiable belief\u2026 e.g. \u201CMid-market brands won\u2019t pay >€10k without SLA\u201D'}
          className="flex-1 px-3 py-2.5 border border-gray-200 rounded-xl bg-white text-sm focus:outline-none focus:ring-2 focus:ring-accent/30"
          aria-invalid={!!validationError}
          aria-describedby={validationError ? 'composer-error' : undefined}
        />
        <button
          type="submit"
          aria-disabled={isDisabled || undefined}
          className={`px-4 py-2.5 rounded-xl text-sm font-semibold bg-accent text-white hover:bg-accent/90 ${isDisabled ? 'opacity-40 cursor-not-allowed' : ''}`}
        >
          Add hypothesis
        </button>
      </form>
      {validationError && (
        <p id="composer-error" className="text-xs text-red-600 mt-1.5" role="alert">
          {validationError}
        </p>
      )}
      {submitError && (
        <p className="text-xs text-red-600 mt-1.5" role="alert">
          Failed to create hypothesis. Please try again.
        </p>
      )}
    </div>
  );
}

// ─── Main Page ───

export function HypothesesPage() {
  const [expandedId, setExpandedId] = useState<number | null>(null);

  const {
    data: hypotheses,
    isLoading,
    isError,
    refetch,
  } = useQuery({
    queryKey: ['hypotheses'],
    queryFn: () => api.listHypotheses(),
  });

  // Loading state
  if (isLoading) {
    return (
      <main className="max-w-3xl mx-auto p-7">
        <h1 className="text-xl font-bold tracking-tight mb-1">Hypotheses</h1>
        <div role="status" aria-label="Loading hypotheses" className="flex justify-center py-12">
          <div className="w-4 h-4 border-2 border-gray-300 border-t-accent rounded-full animate-spin" />
        </div>
      </main>
    );
  }

  // Error state
  if (isError) {
    return (
      <main className="max-w-3xl mx-auto p-7">
        <h1 className="text-xl font-bold tracking-tight mb-1">Hypotheses</h1>
        <div role="alert" className="bg-red-50 border border-red-200 rounded-xl p-4 mt-4">
          <p className="text-sm text-red-700">Failed to load hypotheses.</p>
          <button
            type="button"
            onClick={() => refetch()}
            className="mt-2 text-sm font-semibold text-accent hover:underline"
          >
            Try again
          </button>
        </div>
      </main>
    );
  }

  // Empty state
  if (hypotheses && hypotheses.length === 0) {
    return (
      <main className="max-w-3xl mx-auto p-7">
        <h1 className="text-xl font-bold tracking-tight mb-1">Hypotheses</h1>
        <p className="text-sm text-gray-500 mb-5">
          Falsifiable beliefs, tested against what customers actually said.
        </p>
        <HypothesisComposer />
        <div className="text-center py-12 text-gray-400">
          <p className="text-sm">No hypotheses yet. Add your first falsifiable belief above.</p>
        </div>
      </main>
    );
  }

  return (
    <main className="max-w-3xl mx-auto p-7">
      <h1 className="text-xl font-bold tracking-tight mb-1">Hypotheses</h1>
      <p className="text-sm text-gray-500 mb-5">
        Falsifiable beliefs, tested against what customers actually said.
      </p>

      <HypothesisComposer />

      {hypotheses?.map((hyp) => (
        <HypothesisCard
          key={hyp.id}
          hypothesis={hyp}
          isExpanded={expandedId === hyp.id}
          onToggle={() => setExpandedId(expandedId === hyp.id ? null : hyp.id)}
        />
      ))}
    </main>
  );
}
