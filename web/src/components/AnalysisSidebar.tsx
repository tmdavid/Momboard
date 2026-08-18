import { Analysis, Highlight } from '../api';

interface Props {
  analysis: Analysis | null;
  highlights: Highlight[];
  onJumpToUtterance: (utteranceId: number) => void;
}

export function AnalysisSidebar({ analysis, highlights, onJumpToUtterance }: Props) {
  const result = analysis?.result;

  if (!result) {
    return (
      <aside className="w-[360px] flex-none border-l border-hairline bg-surface overflow-y-auto p-4">
        <div className="text-muted text-sm text-center py-8">
          Analysis will appear here once processing completes.
        </div>
      </aside>
    );
  }

  return (
    <aside className="w-[360px] flex-none border-l border-hairline bg-surface overflow-y-auto p-4">
      {/* Summary */}
      {result.summary && (
        <div className="border border-hairline rounded-xl p-3.5 mb-3.5 bg-page">
          <h3 className="text-xs uppercase tracking-wider text-muted font-semibold mb-2">Summary</h3>
          <p className="text-[13px] text-ink-2">{result.summary}</p>
        </div>
      )}

      {/* Top pains */}
      {result.top_pains && result.top_pains.length > 0 && (
        <div className="border border-hairline rounded-xl p-3.5 mb-3.5 bg-page">
          <h3 className="text-xs uppercase tracking-wider text-muted font-semibold mb-2">Top pains</h3>
          {result.top_pains.map((pain, i) => (
            <div key={i} className="flex gap-2 mb-2 text-[13px]">
              <span
                className={`w-2 h-2 rounded-full mt-1.5 flex-none ${
                  pain.severity === 'high' ? 'bg-crit' : 'bg-warn'
                }`}
              />
              <span>
                {pain.pain}
                {pain.evidence_highlight_ids?.[0] && (
                  <button
                    className="text-accent cursor-pointer text-xs ml-1 whitespace-nowrap bg-transparent border-none"
                    onClick={() => {
                      const hl = highlights.find((h) => h.id === pain.evidence_highlight_ids[0]);
                      if (hl?.utterance_id) onJumpToUtterance(hl.utterance_id);
                    }}
                  >
                    → quote
                  </button>
                )}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Commitments */}
      {result.commitments && result.commitments.length > 0 && (
        <div className="border border-hairline rounded-xl p-3.5 mb-3.5 bg-page">
          <h3 className="text-xs uppercase tracking-wider text-muted font-semibold mb-2">Commitments & advancement</h3>
          {result.commitments.map((c, i) => (
            <div key={i} className="text-[13px] p-2 rounded-lg bg-[#e6f4e6] mb-1.5">
              <b className="text-good-text">{c.type}</b> — {c.next_step || c.what}
              {(c.actor || c.cost) && (
                <span className="block text-xs text-ink-2 mt-0.5">
                  {[c.actor, c.cost].filter(Boolean).join(' · ')}
                </span>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Mom Test critique — #21: explicit labels for Score, Best question, Violations */}
      {result.mom_test_critique && (
        <div className="border border-hairline rounded-xl p-3.5 mb-3.5 bg-page">
          <h3 className="text-xs uppercase tracking-wider text-muted font-semibold mb-2">Mom Test critique</h3>
          <div className="mb-2.5">
            <span className="text-[10px] uppercase tracking-wider text-muted font-semibold">Score</span>
            <div className="flex items-center gap-2 mt-0.5">
              <span className="text-[34px] font-bold tracking-tight">
                {result.mom_test_critique.score}
                <small className="text-sm text-muted font-normal">/10</small>
              </span>
            </div>
          </div>
          {result.mom_test_critique.good_questions && result.mom_test_critique.good_questions.length > 0 && (
            <div className="mb-2.5">
              <span className="text-[10px] uppercase tracking-wider text-muted font-semibold">Best question</span>
              <p className="text-[13px] text-ink-2 mt-0.5">
                "{result.mom_test_critique.good_questions[0]}"
              </p>
            </div>
          )}
          {result.mom_test_critique.violations && result.mom_test_critique.violations.length > 0 && (
            <div>
              <span className="text-[10px] uppercase tracking-wider text-muted font-semibold">Violations</span>
              <div className="mt-1">
                {result.mom_test_critique.violations.map((v, i) => (
                  <div
                    key={i}
                    className="text-xs text-ink-2 py-1.5 px-2 border-l-[3px] border-warn bg-[#fdf6e0] rounded-r-lg mb-1.5"
                  >
                    {v.type.replace(/_/g, ' ')}
                    <span className="block text-good-text mt-0.5">Better: "{v.better}"</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Follow-ups */}
      {result.suggested_followups && result.suggested_followups.length > 0 && (
        <div className="border border-hairline rounded-xl p-3.5 mb-3.5 bg-page">
          <h3 className="text-xs uppercase tracking-wider text-muted font-semibold mb-2">Suggested follow-ups</h3>
          <ul className="list-none">
            {result.suggested_followups.map((f, i) => (
              <li key={i} className="text-[13px] text-ink-2 mb-1.5">
                ☆ {f}
              </li>
            ))}
          </ul>
        </div>
      )}
    </aside>
  );
}
