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
import { useState, useRef, useEffect, FormEvent, KeyboardEvent } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Link, useSearchParams } from 'react-router-dom';
import { positiveInt } from '../utils/queryParams';
import { computeBand, BAND_LABEL, DEFAULT_BAND_RULES } from '../utils/bands';
import { InlineEdit, QuestionsList, BandHistory, AddEvidence } from '../components/HypothesisDetailParts';
import {
  api,
  HypothesisListItem,
  HypothesisDetail,
  HypothesisEvidenceLink,
  HypothesisIntakeResponse,
} from '../api';
import { formatDate, formatNumber } from '../utils/format';

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
  const suggestedContradict = rollup.contradicts.suggested;
  const total = confirmedSupport + confirmedContradict + suggestedSupport + suggestedContradict;

  // Deterministic widths: equal input → identical widths
  const denom = total > 0 ? total : 1;
  const confirmedSupportPct = (confirmedSupport / denom) * 100;
  const suggestedSupportPct = (suggestedSupport / denom) * 100;
  const confirmedContradictPct = (confirmedContradict / denom) * 100;
  const suggestedContradictPct = (suggestedContradict / denom) * 100;
  // Track = remainder (grey)
  const trackPct = 100 - confirmedSupportPct - suggestedSupportPct - confirmedContradictPct - suggestedContradictPct;

  // Label for screen readers
  const ariaLabel = `${confirmedSupport} confirmed support, ${suggestedSupport} suggested support, ${confirmedContradict} confirmed contradictions, ${suggestedContradict} suggested contradictions`;

  return (
    <div
      role="meter"
      aria-label={ariaLabel}
      aria-valuenow={confirmedSupport}
      aria-valuemin={0}
      aria-valuemax={total || 1}
      className="flex-1 h-2 rounded-full bg-gray-200 overflow-hidden flex"
      title={ariaLabel}
    >
      {/* Confirmed support: solid accent */}
      {confirmedSupportPct > 0 && (
        <div
          className="h-full bg-accent"
          style={{ width: `${confirmedSupportPct}%` }}
          data-testid="meter-confirmed-support"
        />
      )}
      {/* Suggested support: hatched accent */}
      {suggestedSupportPct > 0 && (
        <div
          data-testid="meter-suggested"
          className="h-full"
          style={{
            width: `${suggestedSupportPct}%`,
            background: 'repeating-linear-gradient(45deg, var(--color-accent, #2a78d6) 0 3px, transparent 3px 6px)',
            opacity: 0.6,
          }}
        />
      )}
      {/* Confirmed contradictions: solid red */}
      {confirmedContradictPct > 0 && (
        <div
          className="h-full bg-red-500"
          style={{ width: `${confirmedContradictPct}%` }}
          data-testid="meter-confirmed-contradict"
        />
      )}
      {/* Suggested contradictions: hatched red */}
      {suggestedContradictPct > 0 && (
        <div
          className="h-full"
          style={{
            width: `${suggestedContradictPct}%`,
            background: 'repeating-linear-gradient(45deg, #ef4444 0 3px, transparent 3px 6px)',
            opacity: 0.6,
          }}
          data-testid="meter-suggested-contradict"
        />
      )}
      {/* Track: remainder */}
      {trackPct > 0 && (
        <div className="h-full bg-gray-200" style={{ width: `${trackPct}%` }} />
      )}
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

const formatShortDate = formatDate;

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
          href={`/conversations/${link.conversation_id}${link.utterance_id == null ? '' : `#utterance-${link.utterance_id}`}`}
          className="text-xs text-accent whitespace-nowrap hover:underline"
        >
          {link.company_name || link.contact_name || link.conversation_title} ↗
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
      queryClient.invalidateQueries({ queryKey: ['hypothesis-history'] });
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
          {/* Supports section — confirmed */}
          {supportsFiltered.filter(l => l.status === 'confirmed').length > 0 && (
            <>
              <h4 className="text-xs font-bold uppercase tracking-wider text-green-800 mb-2">
                Supports · confirmed
              </h4>
              {supportsFiltered.filter(l => l.status === 'confirmed').map((link) => (
                <EvidenceLinkItem
                  key={link.link_id}
                  link={link}
                  onAccept={() => handleAccept(link.link_id)}
                  onReject={() => handleReject(link.link_id)}
                />
              ))}
            </>
          )}

          {/* Supports section — suggested AI links */}
          {supportsFiltered.filter(l => l.status === 'suggested').length > 0 && (
            <>
              <h4 className="text-xs font-bold uppercase tracking-wider text-yellow-700 mt-3 mb-2">
                Supports · suggested (AI)
              </h4>
              {supportsFiltered.filter(l => l.status === 'suggested').map((link) => (
                <EvidenceLinkItem
                  key={link.link_id}
                  link={link}
                  onAccept={() => handleAccept(link.link_id)}
                  onReject={() => handleReject(link.link_id)}
                />
              ))}
            </>
          )}

          {/* Contradicts section — confirmed */}
          {contradictsFiltered.filter(l => l.status === 'confirmed').length > 0 && (
            <>
              <h4 className="text-xs font-bold uppercase tracking-wider text-red-800 mt-4 mb-2">
                Contradicts · confirmed
              </h4>
              {contradictsFiltered.filter(l => l.status === 'confirmed').map((link) => (
                <EvidenceLinkItem
                  key={link.link_id}
                  link={link}
                  onAccept={() => handleAccept(link.link_id)}
                  onReject={() => handleReject(link.link_id)}
                />
              ))}
            </>
          )}

          {/* Contradicts section — suggested AI links */}
          {contradictsFiltered.filter(l => l.status === 'suggested').length > 0 && (
            <>
              <h4 className="text-xs font-bold uppercase tracking-wider text-yellow-700 mt-3 mb-2">
                Contradicts · suggested (AI)
              </h4>
              {contradictsFiltered.filter(l => l.status === 'suggested').map((link) => (
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

// ─── Grounding bands ───

type BandKey = 'grounded' | 'contested' | 'candidate' | 'hunch' | 'refuted';

const BANDS: { key: BandKey; label: string; dot: string; blurb: string }[] = [
  { key: 'grounded', label: 'Grounded', dot: 'bg-green-500', blurb: 'Customers back it' },
  { key: 'contested', label: 'Contested', dot: 'bg-yellow-500', blurb: 'Customers disagree' },
  { key: 'candidate', label: 'Candidate', dot: 'bg-accent', blurb: 'Some evidence, not enough yet' },
  { key: 'hunch', label: 'Hunch', dot: 'bg-gray-400', blurb: 'No evidence yet' },
  { key: 'refuted', label: 'Refuted', dot: 'bg-red-500', blurb: 'Customers contradict it' },
];

function bandOf(h: HypothesisListItem): BandKey {
  return (h.rollup.grounding as BandKey | undefined) ?? 'hunch';
}

// ─── Hypothesis Card (board) ───

function HypothesisCard({
  hypothesis,
  isExpanded,
  onToggle,
}: {
  hypothesis: HypothesisListItem;
  isExpanded: boolean;
  onToggle: () => void;
}) {
  const { rollup } = hypothesis;
  const suggestedCount = rollup.supports.suggested + rollup.contradicts.suggested;
  const isStale = rollup.freshness === 'stale' && rollup.supports.confirmed > 0;

  return (
    <article
      data-testid="hypothesis-card"
      className={`bg-surface border rounded-[10px] p-3 ${
        isExpanded ? 'border-accent ring-2 ring-accent-soft' : 'border-hairline'
      }`}
    >
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
        className="cursor-pointer flex flex-col gap-2"
      >
        <span className="text-sm font-semibold">{hypothesis.statement}</span>
        <div className="flex flex-wrap items-center gap-1.5">
          {hypothesis.segment && (
            <span className="text-[11px] px-2 py-0.5 rounded-full bg-sub text-ink-2">{hypothesis.segment}</span>
          )}
          {hypothesis.status !== 'open' && <StatusChip status={hypothesis.status} />}
          {suggestedCount > 0 && (
            <span className="text-[11px] text-yellow-800 bg-yellow-50 border border-yellow-200 px-2 py-0.5 rounded-full whitespace-nowrap">
              {formatNumber(suggestedCount)} to review
            </span>
          )}
          {isStale && (
            <span className="text-[11px] text-muted bg-sub px-2 py-0.5 rounded-full">Stale</span>
          )}
        </div>
      </div>
      <div className="mt-2">
        <EvidenceMeter rollup={rollup} />
      </div>
      <EvidenceStats
        rollup={rollup}
        verdict_hint={hypothesis.verdict_hint}
        decided_at={hypothesis.decided_at}
        status={hypothesis.status}
      />
      {rollup.newest_evidence_at && (
        <p className="mt-1 text-[11px] text-muted">Newest quote {formatShortDate(rollup.newest_evidence_at)}</p>
      )}
    </article>
  );
}

// ─── Detail panel (opens under the board) ───

function HypothesisDetailPanel({
  hypothesis,
  onClose,
}: {
  hypothesis: HypothesisListItem;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const band = BANDS.find((b) => b.key === bandOf(hypothesis)) ?? BANDS[3];

  const { data: detail } = useQuery({
    queryKey: ['hypothesis', hypothesis.id],
    queryFn: () => api.getHypothesis(hypothesis.id),
  });

  const allEvidence = [...(detail?.evidence.supports ?? []), ...(detail?.evidence.contradicts ?? [])];
  const linkedIds = new Set(allEvidence.map((e) => e.highlight_id));
  const confirmedHighlightIds = (detail?.evidence.supports ?? [])
    .filter((e) => e.status === 'confirmed')
    .map((e) => e.highlight_id);

  const statusMutation = useMutation({
    mutationFn: (newStatus: string) => api.updateHypothesis(hypothesis.id, { status: newStatus }),
    onSuccess: (data) => {
      queryClient.setQueryData<HypothesisListItem[]>(['hypotheses'], (old) =>
        (old || [])
          .filter((h) => !(h.id === hypothesis.id && data.status === 'archived'))
          .map((h) =>
            h.id === hypothesis.id
              ? { ...h, status: data.status, decided_at: data.decided_at ?? h.decided_at }
              : h,
          ),
      );
      if (data.status === 'archived') {
        queryClient.invalidateQueries({ queryKey: ['hypotheses', 'archived'] });
        onClose();
      }
    },
  });

  return (
    <div
      role="group"
      aria-label={`Hypothesis detail: ${hypothesis.statement}`}
      data-testid="hypothesis-detail"
      className="bg-surface border border-hairline rounded-xl p-4"
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-ink">
          <span className={`w-2 h-2 rounded-full ${band.dot}`} aria-hidden="true" />
          {band.label}
        </span>
        {hypothesis.segment && (
          <span className="text-[11px] px-2 py-0.5 rounded-full bg-sub text-ink-2">{hypothesis.segment}</span>
        )}
        <span className="flex-1" />
        <button
          type="button"
          onClick={() => statusMutation.mutate('archived')}
          disabled={statusMutation.isPending}
          className="text-xs font-semibold text-muted hover:text-ink border border-hairline rounded-lg px-2.5 py-1"
        >
          Archive
        </button>
        <button
          type="button"
          onClick={onClose}
          className="text-xs font-semibold text-muted hover:text-ink border border-hairline rounded-lg px-2.5 py-1"
        >
          Close
        </button>
      </div>
      {hypothesis.rollup.grounding_reason && (
        <p className="mt-2 text-sm text-ink-2" data-testid="grounding-reason">
          {hypothesis.rollup.grounding_reason}
        </p>
      )}
      <div className="mt-1">
        <InlineEdit
          id={hypothesis.id}
          statement={hypothesis.statement}
          segment={hypothesis.segment}
          hasEvidenceLinks={(detail?.evidence.supports.length ?? 0) + (detail?.evidence.contradicts.length ?? 0) > 0}
        />
      </div>
      {detail && (
        <>
          <EvidenceSection
            evidence={detail.evidence}
            hypothesisStatus={hypothesis.status}
            onStatusChange={(status) => statusMutation.mutate(status)}
          />
          <AddEvidence hypothesisId={hypothesis.id} linkedHighlightIds={linkedIds} />
          <QuestionsList hypothesisId={hypothesis.id} questions={detail.questions ?? []} />
          <BandHistory hypothesisId={hypothesis.id} />
          <div className="mt-4 border-t border-hairline pt-3">
            {confirmedHighlightIds.length > 0 ? (
              <Link
                to={`/decisions?hypothesis_id=${hypothesis.id}${confirmedHighlightIds
                  .map((id) => `&highlight_id=${id}`)
                  .join('')}`}
                className="text-sm font-semibold"
              >
                Cite in decision
              </Link>
            ) : (
              <span className="text-xs text-muted">
                Confirm at least one quote to cite this hypothesis in a decision.
              </span>
            )}
          </div>
        </>
      )}
    </div>
  );
}

// ─── Composer ───

type IntakeMatch = NonNullable<HypothesisIntakeResponse['matches']>[number];

/** Band the belief would have if saved with the ticked quotes (same rules as the server). */
/** Stable identity of a match: 'h<id>' when tagged, 'u<utterance id>' for untagged speech. */
function matchKey(m: IntakeMatch): string {
  return m.key || (m.highlight_id != null ? `h${m.highlight_id}` : `u${m.utterance_id ?? ''}`);
}

function previewBand(
  matches: IntakeMatch[],
  ticked: Set<string>,
  rules: typeof DEFAULT_BAND_RULES,
): string {
  const chosen = matches.filter((m) => ticked.has(matchKey(m)));
  const supports = chosen.filter((m) => m.relation === 'supports');
  const companies = new Set(supports.map((m) => m.company_name).filter(Boolean));
  const contradicts = chosen.length - supports.length;
  return BAND_LABEL[computeBand(supports.length, contradicts, companies.size, rules)];
}

function matchSource(m: IntakeMatch): string {
  return [m.company_name, m.contact_name, m.conversation_date ? formatDate(m.conversation_date) : null].filter(Boolean).join(' · ');
}

function IntakeMatchRow({
  match,
  checked,
  onToggle,
}: {
  match: IntakeMatch;
  checked: boolean;
  onToggle: (checked: boolean) => void;
}) {
  const source = matchSource(match);
  return (
    <li className="flex items-start gap-2 text-sm">
      <input
        type="checkbox"
        className="mt-1"
        aria-label={`Confirm evidence ${match.highlight_id ?? `u${match.utterance_id}`}`}
        checked={checked}
        onChange={(e) => onToggle(e.target.checked)}
      />
      <div className="flex-1">
        <span
          className={`text-[11px] font-semibold uppercase mr-1.5 ${
            match.relation === 'contradicts' ? 'text-crit' : 'text-good-text'
          }`}
        >
          {match.relation}
        </span>
        <span className="italic">“{match.quote}”</span>
        {match.rationale && <span className="block text-xs text-muted">{match.rationale}</span>}
        {source && <span className="block text-xs text-muted">{source}</span>}
      </div>
      {typeof match.confidence === 'number' && (
        <span className="text-xs text-muted tabular-nums whitespace-nowrap" title="Match score">
          match {match.confidence.toFixed(2)}
        </span>
      )}
    </li>
  );
}

function HypothesisComposer() {
  const [statement, setStatement] = useState('');
  const [segment, setSegment] = useState('');
  const [validationError, setValidationError] = useState('');
  const [submitError, setSubmitError] = useState(false);
  const queryClient = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);

  // Segment suggestions: segments already in use (server-side distinct list).
  const { data: segmentData } = useQuery({
    queryKey: ['hypothesis-segments'],
    queryFn: () => api.hypothesisSegments(),
    staleTime: 60_000,
  });
  const segmentSuggestions = segmentData?.items ?? [];

  // Live band rules (server settings) so the preview matches how the server will band it.
  const { data: rulesData } = useQuery({
    queryKey: ['hypothesis-band-rules'],
    queryFn: () => api.hypothesisBandRules(),
    staleTime: 10 * 60_000,
  });
  const bandRules = rulesData ?? DEFAULT_BAND_RULES;

  // T48: evidence-gated intake — preview matches, confirm per-quote, then commit.
  const [preview, setPreview] = useState<HypothesisIntakeResponse | null>(null);
  const [confirmedIds, setConfirmedIds] = useState<Set<string>>(new Set());

  const previewMutation = useMutation({
    mutationFn: (body: { statement: string; segment?: string }) => api.intakePreview(body),
    onSuccess: (data) => {
      setPreview(data);
      // Strong matches (direct, high-confidence) start ticked; weaker ones start unticked.
      setConfirmedIds(
        new Set((data.matches ?? []).filter((m) => m.strong).map(matchKey)),
      );
    },
  });

  const resetComposer = () => {
    setStatement('');
    setSegment('');
    setPreview(null);
    setConfirmedIds(new Set());
    previewMutation.reset();
  };

  const commitMutation = useMutation({
    mutationFn: (body: Parameters<typeof api.intakeCommit>[0]) => api.intakeCommit(body),
    onSuccess: () => {
      resetComposer();
      queryClient.invalidateQueries({ queryKey: ['hypotheses'] });
      queryClient.invalidateQueries({ queryKey: ['hypothesis-segments'] });
    },
  });

  const createMutation = useMutation({
    mutationFn: (body: { statement: string; segment?: string }) => api.createHypothesis(body),
    onMutate: async (body) => {
      await queryClient.cancelQueries({ queryKey: ['hypotheses'] });
      const previous = queryClient.getQueryData<HypothesisListItem[]>(['hypotheses']);

      const optimistic: HypothesisListItem = {
        id: -Date.now(),
        statement: body.statement,
        segment: body.segment ?? null,
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
          grounding: 'hunch',
          pending_count: 0,
          grounding_reason: 'No evidence yet.',
        },
        verdict_hint: null,
      };

      queryClient.setQueryData<HypothesisListItem[]>(
        ['hypotheses'],
        (old) => [optimistic, ...(old || [])],
      );

      resetComposer();
      setValidationError('');
      setSubmitError(false);

      return { previous, optimisticId: optimistic.id };
    },
    onError: (_err, _body, context) => {
      if (context?.previous) {
        queryClient.setQueryData(['hypotheses'], context.previous);
      }
      setSubmitError(true);
    },
    onSuccess: (data, _body, context) => {
      // The mutation endpoint returns the base hypothesis fields only. Preserve
      // the optimistic card's empty rollup until the authoritative list refetch.
      queryClient.setQueryData<HypothesisListItem[]>(
        ['hypotheses'],
        (old) =>
          (old || []).map((h) =>
            h.id === context?.optimisticId
              ? { ...h, ...data, rollup: h.rollup, verdict_hint: h.verdict_hint }
              : h,
          ),
      );
    },
  });

  const trimmed = statement.trim();
  const trimmedSegment = segment.trim();

  const handleSubmit = (e?: FormEvent) => {
    e?.preventDefault();
    if (trimmed.length < 15) {
      setValidationError('Statement must be at least 15 characters');
      return;
    }
    setValidationError('');
    createMutation.mutate({
      statement: trimmed,
      ...(trimmedSegment ? { segment: trimmedSegment } : {}),
    });
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleSubmit();
    }
  };

  const runCheck = () =>
    previewMutation.mutate({
      statement: trimmed,
      ...(trimmedSegment ? { segment: trimmedSegment } : {}),
    });

  const trimmedLength = trimmed.length;
  const isDisabled = trimmedLength === 0;

  const matches = [...(preview?.matches ?? [])].sort(
    (a, b) => (b.confidence ?? 0) - (a.confidence ?? 0),
  );
  const strongMatches = matches.filter((m) => m.strong);
  const weakMatches = matches.filter((m) => !m.strong);
  const questions = preview?.suggested_questions ?? [];
  const toggle = (id: string) => (checked: boolean) =>
    setConfirmedIds((prev) => {
      const next = new Set(prev);
      if (checked) next.add(id);
      else next.delete(id);
      return next;
    });

  return (
    <div className="bg-surface border border-hairline rounded-xl p-4 flex flex-col gap-3">
      <form onSubmit={handleSubmit} className="flex flex-wrap gap-2 items-end">
        <label className="flex-1 min-w-[260px] flex flex-col gap-1">
          <span className="text-xs font-semibold text-muted">Belief · name a segment and a behaviour</span>
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
            className="w-full h-10 px-3 border border-hairline rounded-lg bg-surface text-sm"
            aria-invalid={!!validationError}
            aria-describedby={validationError ? 'composer-error' : 'composer-help'}
          />
        </label>
        <label className="w-44 flex flex-col gap-1">
          <span className="text-xs font-semibold text-muted">Segment (optional)</span>
          <input
            type="text"
            value={segment}
            onChange={(e) => setSegment(e.target.value)}
            list="hypothesis-segments"
            placeholder="e.g. Mid-market"
            className="w-full h-10 px-3 border border-hairline rounded-lg bg-surface text-sm"
          />
          <datalist id="hypothesis-segments">
            {segmentSuggestions.map((sg) => (
              <option key={sg} value={sg} />
            ))}
          </datalist>
        </label>
        <button
          type="submit"
          aria-disabled={isDisabled || undefined}
          className={`h-10 px-4 rounded-lg text-sm font-semibold ${
            isDisabled ? 'bg-sub text-muted cursor-not-allowed' : 'border border-hairline bg-surface text-ink hover:border-accent'
          }`}
        >
          Add hypothesis
        </button>
        <button
          type="button"
          disabled={trimmedLength < 15 || previewMutation.isPending}
          onClick={runCheck}
          className="h-10 px-4 rounded-lg text-sm font-semibold border-none bg-accent text-white hover:bg-[#2448c7] disabled:opacity-50"
        >
          {previewMutation.isPending ? 'Checking…' : 'Check evidence first'}
        </button>
      </form>
      {/* #17: Helper text naming segment + behavior format */}
      <p id="composer-help" className="text-xs text-muted mt-1.5">
        Name a <b>segment</b> + <b>behavior</b>. Example: "Enterprise ops teams won't switch without SSO."
      </p>
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
      {previewMutation.isError && !preview && (
        <div className="flex items-center gap-3 text-xs text-red-700" role="alert">
          <span>Couldn’t check the evidence right now. Your belief is kept.</span>
          <button
            type="button"
            onClick={() => handleSubmit()}
            className="font-semibold text-accent hover:underline"
          >
            Save as hunch
          </button>
        </div>
      )}
      {preview && (
        <div className="mt-3 border border-hairline rounded-xl bg-surface p-4" data-testid="intake-panel">
          {matches.length > 0 ? (
            <>
              <p className="text-xs text-muted mb-2">
                Untick any quote that isn’t genuinely evidence for this belief. Only ticked quotes are saved.
              </p>
              <ul className="space-y-2">
                {strongMatches.map((m) => (
                  <IntakeMatchRow
                    key={matchKey(m)}
                    match={m}
                    checked={confirmedIds.has(matchKey(m))}
                    onToggle={toggle(matchKey(m))}
                  />
                ))}
              </ul>
              {weakMatches.length > 0 && (
                <>
                  <p className="mt-3 mb-2 text-xs font-semibold text-muted border-t border-hairline pt-2">
                    Weaker matches
                  </p>
                  <ul className="space-y-2">
                    {weakMatches.map((m) => (
                      <IntakeMatchRow
                        key={matchKey(m)}
                        match={m}
                        checked={confirmedIds.has(matchKey(m))}
                        onToggle={toggle(matchKey(m))}
                      />
                    ))}
                  </ul>
                </>
              )}
              <p className="mt-3 text-xs text-muted" data-testid="band-preview">
                If saved now: <b className="text-ink">{previewBand(matches, confirmedIds, bandRules)}</b>
              </p>
            </>
          ) : (
            <p className="text-sm text-muted">
              No supporting evidence found in the calls — this would save as a <b>hunch</b>.
              {questions.length > 0 && ' Go validate it with:'}
            </p>
          )}
          {questions.length > 0 && (
            <div className="mt-3 rounded-lg bg-sub p-3">
              <p className="text-xs font-semibold text-muted mb-1">Ask next to test it</p>
              <ul className="space-y-1">
                {questions.map((q, i) => (
                  <li key={i} className="flex items-start gap-2 text-xs text-ink-2">
                    <span className="flex-1">{q}</span>
                    <button
                      type="button"
                      aria-label={`Copy question ${i + 1}`}
                      onClick={() => void navigator.clipboard?.writeText(q)}
                      className="text-accent hover:underline"
                    >
                      Copy
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <div className="flex items-center gap-3 mt-3">
            <button
              type="button"
              onClick={() => {
                const confirmed = matches
                  .filter((m) => confirmedIds.has(matchKey(m)))
                  .map((m) =>
                    m.highlight_id != null
                      ? { highlight_id: m.highlight_id, stance: m.relation as 'supports' | 'contradicts' }
                      : {
                          // Untagged customer speech: the server records it as an accepted highlight.
                          utterance_id: m.utterance_id as number,
                          quote: m.quote,
                          stance: m.relation as 'supports' | 'contradicts',
                        },
                  );
                const seg = trimmedSegment || preview.segment || undefined;
                commitMutation.mutate({
                  statement: preview.statement,
                  segment: seg,
                  confirmed,
                  validation_questions: questions,
                });
              }}
              disabled={commitMutation.isPending}
              className="px-4 py-2 rounded-xl text-sm font-semibold bg-accent text-white hover:bg-[#1c5cab] disabled:opacity-50"
            >
              {confirmedIds.size > 0
                ? `Save with ${confirmedIds.size} ${confirmedIds.size === 1 ? 'quote' : 'quotes'}`
                : 'Save as hunch'}
            </button>
            <button
              type="button"
              onClick={() => setPreview(null)}
              className="text-sm text-muted hover:text-ink-2"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Main Page ───

// ─── Archived hypotheses (restore) ───

function ArchivedSection() {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const { data, isLoading, isError } = useQuery({
    queryKey: ['hypotheses', 'archived'],
    queryFn: () => api.listHypotheses({ status: 'archived' }),
    enabled: open,
  });
  const restore = useMutation({
    mutationFn: (id: number) => api.updateHypothesis(id, { status: 'open' }),
    // Prefix match refreshes both the board and this list.
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['hypotheses'] }),
  });
  const items = data ?? [];

  return (
    <div role="group" aria-label="Archived hypotheses" className="flex flex-col gap-2">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="self-start text-xs font-semibold text-muted hover:text-ink bg-transparent border-none p-0 cursor-pointer"
      >
        {open ? 'Hide archived' : 'Show archived'}
      </button>
      {open && isLoading && <p className="text-xs text-muted">Loading archived…</p>}
      {open && isError && (
        <p role="alert" className="text-xs text-red-600">Couldn’t load archived hypotheses.</p>
      )}
      {open && !isLoading && !isError && items.length === 0 && (
        <p className="text-xs text-muted">Nothing archived.</p>
      )}
      {open && items.length > 0 && (
        <ul className="flex flex-col gap-2 m-0 p-0 list-none">
          {items.map((h) => (
            <li
              key={h.id}
              data-testid="archived-hypothesis"
              className="flex items-center gap-3 bg-surface border border-hairline rounded-[10px] px-3 py-2 opacity-80"
            >
              <span className="flex-1 min-w-0 text-sm text-ink-2">
                {h.statement}
                {h.segment && (
                  <span className="ml-2 text-[11px] px-2 py-0.5 rounded-full bg-sub text-ink-2">{h.segment}</span>
                )}
              </span>
              <button
                type="button"
                disabled={restore.isPending}
                onClick={() => restore.mutate(h.id)}
                aria-label={`Restore: ${h.statement}`}
                className="text-xs font-semibold px-2.5 py-1 rounded-lg border border-hairline text-accent hover:border-accent"
              >
                Restore
              </button>
            </li>
          ))}
        </ul>
      )}
      {restore.isError && (
        <p role="alert" className="text-xs text-red-600">Couldn’t restore that hypothesis. Try again.</p>
      )}
    </div>
  );
}

function BandRulesHelp() {
  const [open, setOpen] = useState(false);
  const { data } = useQuery({
    queryKey: ['hypothesis-band-rules'],
    queryFn: () => api.hypothesisBandRules(),
    staleTime: 10 * 60_000,
  });
  if (!data) return null;
  return (
    <details
      className="text-sm text-ink-2"
      data-testid="band-rules-help"
      onToggle={(e) => setOpen((e.currentTarget as HTMLDetailsElement).open)}
    >
      <summary className="cursor-pointer text-xs font-semibold text-muted">How bands work</summary>
      {open && (
        <>
          <ul className="mt-2 space-y-1">
            {data.items.map((r) => (
              <li key={r.band}>
                <b className="text-ink">{r.label}</b> — {r.rule}
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-muted">
            Only quotes you have confirmed count. Suggested matches wait for your review and never move a band.
          </p>
        </>
      )}
    </details>
  );
}

const BAND_EXPLAINER =
  'Hypotheses sit in a band by the quotes you have confirmed: Grounded, Contested, Candidate, Hunch or Refuted.';

export function HypothesesPage() {
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [segmentFilter, setSegmentFilter] = useState('');
  const [bandFilter, setBandFilter] = useState('');
  const [pendingOnly, setPendingOnly] = useState(false);

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
  // A link to one belief (/hypotheses?hypothesis=7, as cited by the MCP tools) opens its detail once.
  // These hooks sit above the early returns below: hooks must run in the same order on every render.
  const [searchParams] = useSearchParams();
  const linkedConsumed = useRef(false);
  const linkedId = positiveInt(searchParams.get('hypothesis'));
  useEffect(() => {
    if (linkedConsumed.current || linkedId == null || !hypotheses?.some((h) => h.id === linkedId)) return;
    linkedConsumed.current = true;
    setExpandedId(linkedId);
  }, [linkedId, hypotheses]);

  if (isLoading) {
    return (
      <main className="p-6 flex flex-col gap-5">
        <h1 className="text-2xl font-bold text-ink">Hypotheses</h1>
        <div role="status" aria-label="Loading hypotheses" className="flex justify-center py-12">
          <div className="w-4 h-4 border-2 border-gray-300 border-t-accent rounded-full animate-spin" />
        </div>
      </main>
    );
  }

  // Error state
  if (isError) {
    return (
      <main className="p-6 flex flex-col gap-5">
        <h1 className="text-2xl font-bold text-ink">Hypotheses</h1>
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
      <main className="p-6 flex flex-col gap-5">
        <h1 className="text-2xl font-bold text-ink">Hypotheses</h1>
        <p className="text-sm text-gray-500 mb-5">
          Falsifiable beliefs, tested against what customers actually said.
        </p>
        <HypothesisComposer />
        <div className="text-center py-12 text-gray-400">
          <p className="text-sm">No hypotheses yet. Add your first falsifiable belief above.</p>
          <p className="text-xs mt-2">{BAND_EXPLAINER}</p>
          <div className="mt-3 text-left max-w-xl mx-auto"><BandRulesHelp /></div>
        </div>
        <ArchivedSection />
      </main>
    );
  }

  const all = hypotheses ?? [];
  const segments = Array.from(
    new Set(all.map((h) => h.segment).filter((x): x is string => !!x)),
  ).sort();
  const visible = all.filter(
    (h) =>
      (!segmentFilter || h.segment === segmentFilter) &&
      (!bandFilter || bandOf(h) === bandFilter) &&
      (!pendingOnly || (h.rollup.pending_count ?? h.rollup.supports.suggested + h.rollup.contradicts.suggested) > 0),
  );
  const expanded = all.find((h) => h.id === expandedId) ?? null;

  return (
    <main className="p-6 flex flex-col gap-5">
      <h1 className="text-2xl font-bold text-ink">Hypotheses</h1>
      <p className="text-sm text-gray-500 mb-5">
        Falsifiable beliefs, tested against what customers actually said.
      </p>

      <HypothesisComposer />

      <div className="flex flex-wrap items-center gap-3" role="group" aria-label="Board filters">
        <label className="flex items-center gap-1.5 text-xs text-muted">
          Segment
          <select
            value={segmentFilter}
            onChange={(e) => setSegmentFilter(e.target.value)}
            className="h-8 px-2 border border-hairline rounded-lg bg-surface text-sm text-ink"
          >
            <option value="">All segments</option>
            {segments.map((sg) => (
              <option key={sg} value={sg}>{sg}</option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-1.5 text-xs text-muted">
          Band
          <select
            value={bandFilter}
            onChange={(e) => setBandFilter(e.target.value)}
            className="h-8 px-2 border border-hairline rounded-lg bg-surface text-sm text-ink"
          >
            <option value="">All bands</option>
            {BANDS.map((b) => (
              <option key={b.key} value={b.key}>{b.label}</option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-1.5 text-xs text-muted">
          <input
            type="checkbox"
            checked={pendingOnly}
            onChange={(e) => setPendingOnly(e.target.checked)}
          />
          Has pending suggestions
        </label>
      </div>

      <BandRulesHelp />

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-5 gap-3 items-start">
        {BANDS.map((band) => {
          const inBand = visible.filter((h) => bandOf(h) === band.key);
          return (
            <div
              key={band.key}
              role="group"
              aria-label={`${band.label} hypotheses`}
              data-testid={`band-${band.key}`}
              className="flex flex-col gap-2 min-w-0"
            >
              <header className="flex items-center gap-2 px-1">
                <span className={`w-2 h-2 rounded-full ${band.dot}`} aria-hidden="true" />
                <h2 className="text-sm font-semibold text-ink">{band.label}</h2>
                <span className="text-xs text-muted tabular-nums">{inBand.length}</span>
              </header>
              {inBand.length === 0 ? (
                <p className="text-xs text-muted px-1">{band.blurb}</p>
              ) : (
                inBand.map((hyp) => (
                  <HypothesisCard
                    key={hyp.id}
                    hypothesis={hyp}
                    isExpanded={expandedId === hyp.id}
                    onToggle={() => setExpandedId(expandedId === hyp.id ? null : hyp.id)}
                  />
                ))
              )}
            </div>
          );
        })}
      </div>

      {expanded && (
        <HypothesisDetailPanel hypothesis={expanded} onClose={() => setExpandedId(null)} />
      )}

      <ArchivedSection />
    </main>
  );
}
