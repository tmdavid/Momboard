import { useState } from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { scoreBand } from '../constants';
import { formatDate } from '../utils/format';

interface PersonaResult {
  id: number;
  kind: string;
  result: {
    name: string;
    role: string;
    company_profile: string;
    traits: { trait: string; evidence_highlight_ids: number[] }[];
    sore_points: string[];
    vocabulary_hints: string[];
  };
}

interface Turn {
  role: 'user' | 'persona';
  text: string;
}

interface SessionResult {
  id: number;
  title: string;
  status: string;
  meta: Record<string, unknown> | null;
  analysis: {
    id: number;
    kind: string;
    result: {
      mom_test_critique?: { score: number; good_questions: string[]; violations: { utterance_idx: number; type: string; better: string }[] };
      summary?: string;
    } | null;
    created_at: string | null;
  } | null;
}

interface PastSession {
  id: number;
  title: string;
  status: string;
  created_at: string | null;
  score: number | null;
  has_analysis: boolean;
}

export function SimulatorPage() {
  const [sessionId, setSessionId] = useState<number | null>(null);
  const [persona, setPersona] = useState<PersonaResult | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState('');
  const [sessionResult, setSessionResult] = useState<SessionResult | null>(null);
  const [isPolling, setIsPolling] = useState(false);
  const [endedSessionId, setEndedSessionId] = useState<number | null>(null);
  const [filterCompanyId, setFilterCompanyId] = useState<string>('');
  const [filterTag, setFilterTag] = useState<string>('');

  const { data: companies } = useQuery({ queryKey: ['companies', 'active'], queryFn: () => api.listActiveCompanies() });
  const { data: tags } = useQuery({ queryKey: ['tags'], queryFn: () => api.listTags() });
  const { data: pastSessions, isLoading: sessionsLoading, error: sessionsError } = useQuery({
    queryKey: ['simulator-sessions'],
    queryFn: () => api.listSimulatorSessions(),
  });

  const buildPersona = useMutation({
    mutationFn: async () => {
      const filters: Record<string, unknown> = {};
      if (filterCompanyId) filters.company_id = parseInt(filterCompanyId);
      if (filterTag) filters.tag_key = filterTag;
      const r = await fetch('/api/simulator/personas', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filters: Object.keys(filters).length ? filters : null }),
      });
      if (!r.ok) throw new Error('Failed to build persona');
      return r.json() as Promise<PersonaResult>;
    },
    onSuccess: (data) => setPersona(data),
  });

  const createSession = useMutation({
    mutationFn: async (personaId: number) => {
      const r = await fetch('/api/simulator/sessions', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ persona_id: personaId }),
      });
      if (!r.ok) throw new Error('Failed to create session');
      return r.json() as Promise<{ id: number }>;
    },
    onSuccess: (data) => { setSessionId(data.id); setTurns([]); setSessionResult(null); setEndedSessionId(null); },
  });

  const sendTurn = useMutation({
    mutationFn: async (text: string) => {
      if (!sessionId) throw new Error('No session');
      const r = await fetch(`/api/simulator/sessions/${sessionId}/turns`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }),
      });
      if (!r.ok) throw new Error('Failed to send turn');
      return r.json() as Promise<{ reply: string }>;
    },
    onSuccess: (data, text) => {
      setTurns((prev) => [...prev, { role: 'user', text }, { role: 'persona', text: data.reply }]);
      setInput('');
    },
  });

  const endSession = useMutation({
    mutationFn: async () => {
      if (!sessionId) throw new Error('No session');
      const r = await fetch(`/api/simulator/sessions/${sessionId}/end`, { method: 'POST' });
      if (!r.ok) { const err = await r.json().catch(() => ({ detail: 'Failed' })); throw new Error(err.detail || 'Failed to end session'); }
      return r.json();
    },
    onSuccess: () => {
      const sid = sessionId!;
      setEndedSessionId(sid); setSessionId(null); setIsPolling(true);
      pollForResult(sid);
    },
  });

  const pollForResult = async (sid: number) => {
    for (let i = 0; i < 15; i++) {
      try {
        const r = await fetch(`/api/simulator/sessions/${sid}/result`);
        if (r.ok) {
          const data: SessionResult = await r.json();
          if (data.analysis?.result) { setSessionResult(data); setIsPolling(false); return; }
        }
      } catch { /* retry */ }
      await new Promise((resolve) => setTimeout(resolve, 2000));
    }
    try { const r = await fetch(`/api/simulator/sessions/${sid}/result`); if (r.ok) setSessionResult(await r.json()); } catch { /* ignore */ }
    setIsPolling(false);
  };

  const handleSend = () => { if (input.trim()) sendTurn.mutate(input.trim()); };
  const critique = sessionResult?.analysis?.result?.mom_test_critique ?? null;

  // v0.5 U10: after a reload nothing was scored "in this visit", so fall back to the newest finished
  // session in the list. The list's own score is shown at once so the panel can never contradict it;
  // the critique details load behind it.
  const latestFinished = pastSessions?.items.find((s: PastSession) => s.score != null) ?? null;
  const { data: latestDetail } = useQuery({
    queryKey: ['simulator-result', latestFinished?.id],
    enabled: latestFinished != null && !critique,
    retry: false,
    queryFn: async () => {
      const r = await fetch(`/api/simulator/sessions/${latestFinished!.id}/result`);
      if (!r.ok) throw new Error('result unavailable');
      return (await r.json()) as SessionResult;
    },
  });
  const latestCritique = latestDetail?.analysis?.result?.mom_test_critique ?? null;

  const shown = critique
    ? { label: 'Last session · scored', score: critique.score, good_questions: critique.good_questions, violations: critique.violations }
    : latestFinished && latestFinished.score != null
      ? {
          label: `Last finished session · ${formatDate(latestFinished.created_at)}`,
          score: latestFinished.score,
          good_questions: latestCritique?.good_questions ?? [],
          violations: latestCritique?.violations ?? [],
        }
      : null;
  const inSession = !!sessionId && !isPolling && !sessionResult;

  return (
    <main className="p-6 flex flex-col gap-4">
      <div className="flex flex-col gap-0.5">
        <h1 className="text-2xl font-bold text-ink">Practice interview</h1>
        <span className="text-muted">Rehearse with an AI customer built from your real conversations, then get scored</span>
      </div>

      <div className="flex flex-wrap gap-4 items-start">
        {/* ── Left: persona + past sessions ── */}
        <aside className="flex-[1_1_280px] max-w-[340px] flex flex-col gap-3">
          <section className="bg-surface border border-hairline rounded-[10px] p-4 flex flex-col gap-2.5" aria-label="Persona">
            <span className="text-xs font-semibold text-muted">Build persona from</span>
            <label className="flex flex-col gap-1">
              <span className="text-[13px]">Company</span>
              <select value={filterCompanyId} onChange={(e) => setFilterCompanyId(e.target.value)}
                className="h-9 px-3 border border-hairline rounded-lg text-sm bg-surface text-ink" aria-label="Simulator persona company filter">
                <option value="">All companies</option>
                {companies?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-[13px]">Tag</span>
              <select value={filterTag} onChange={(e) => setFilterTag(e.target.value)}
                className="h-9 px-3 border border-hairline rounded-lg text-sm bg-surface text-ink" aria-label="Simulator persona tag filter">
                <option value="">All tags</option>
                {tags?.map((t) => <option key={t.key} value={t.key}>{t.emoji} {t.name}</option>)}
              </select>
            </label>
            <button onClick={() => buildPersona.mutate()} disabled={buildPersona.isPending}
              className="h-9 rounded-lg border border-hairline bg-surface text-ink font-semibold hover:border-accent disabled:opacity-50">
              {buildPersona.isPending ? 'Building…' : persona ? 'Rebuild Persona' : 'Build Persona'}
            </button>

            {persona && (
              <div className="border-t border-sub pt-2.5 flex flex-col gap-1.5">
                <span className="font-semibold text-ink">{persona.result.name}</span>
                <span className="text-[13px] text-ink-2">{persona.result.role} — {persona.result.company_profile}</span>
                {persona.result.sore_points.length > 0 && (
                  <>
                    <span className="text-xs font-semibold text-muted mt-1">Sore points</span>
                    <span className="text-[13px] text-ink-2">{persona.result.sore_points.join(' · ')}</span>
                  </>
                )}
                {!sessionId && (
                  <button onClick={() => createSession.mutate(persona.id)} disabled={createSession.isPending}
                    className="mt-1 h-9 rounded-lg border-none bg-accent text-white font-semibold hover:bg-[#2448c7] disabled:opacity-50">
                    {createSession.isPending ? 'Starting…' : 'Start Session'}
                  </button>
                )}
              </div>
            )}
          </section>

          <section className="bg-surface border border-hairline rounded-[10px] p-4 flex flex-col gap-1" aria-label="Past sessions" data-testid="past-sessions">
            <span className="text-xs font-semibold text-muted mb-1">Past sessions</span>
            {sessionsLoading && <p className="text-sm text-muted">Loading sessions…</p>}
            {sessionsError && <p className="text-sm text-crit" role="alert">Failed to load past sessions.</p>}
            {!sessionsLoading && !sessionsError && pastSessions && pastSessions.items.length === 0 && (
              <p className="text-sm text-muted" data-testid="no-past-sessions">No practice sessions yet. Build a persona and start practicing!</p>
            )}
            {!sessionsLoading && pastSessions && pastSessions.items.map((s: PastSession) => (
              <Link key={s.id} to={`/conversations/${s.id}`} data-testid="past-session-item"
                className="flex items-center gap-2 py-1.5 border-t border-sub text-ink-2 hover:text-accent">
                <span className="trunc text-sm">{s.title}</span>
                {s.score != null && (
                  <span className={`ml-auto text-xs font-semibold px-2 py-0.5 rounded-pill ${scoreBand(s.score).cls}`}>{s.score}/10</span>
                )}
              </Link>
            ))}
          </section>
        </aside>

        {/* ── Center: live chat ── */}
        <section className="flex-[999_1_460px] min-w-0 bg-surface border border-hairline rounded-xl flex flex-col" aria-label="Session">
          <div className="p-3 px-4 border-b border-hairline flex items-center gap-2">
            {inSession ? (
              <>
                <span className="w-2 h-2 rounded-pill bg-good" aria-hidden="true" />
                <span className="font-semibold text-ink">Session in progress</span>
                <span className="text-xs text-muted">{turns.filter((t) => t.role === 'user').length} questions asked</span>
                <button onClick={() => endSession.mutate()} disabled={endSession.isPending || turns.length === 0}
                  className="ml-auto h-8 px-3 rounded-lg border border-hairline bg-surface text-ink font-semibold hover:border-accent disabled:opacity-50">
                  End & Score
                </button>
              </>
            ) : (
              <span className="font-semibold text-ink">{isPolling || sessionResult ? 'Session Complete' : 'No active session'}</span>
            )}
          </div>

          <div className="p-4 flex flex-col gap-3 min-h-[320px]" role="log" aria-label="Conversation">
            {!persona && !sessionResult && !isPolling && (
              <p className="text-muted italic">Build a persona on the left to start a practice session.</p>
            )}
            {persona && !inSession && !isPolling && !sessionResult && (
              <p className="text-muted italic">Start a session from the persona card to begin.</p>
            )}
            {isPolling && (
              <div className="flex items-center gap-2 text-muted" role="status">
                <span className="w-4 h-4 border-2 border-hairline border-t-accent rounded-full animate-spin" aria-hidden="true" />
                Scoring your interview…
              </div>
            )}
            {inSession && turns.length === 0 && (
              <p className="text-muted italic">Start the conversation. Ask about their past experiences.</p>
            )}
            {(inSession || sessionResult) && turns.map((turn, i) => (
              <div key={i} className={`flex ${turn.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <span className={`inline-block max-w-[78%] px-3.5 py-2.5 rounded-xl text-sm ${
                  turn.role === 'user' ? 'bg-accent text-white rounded-br-[4px]' : 'bg-sub text-ink rounded-bl-[4px]'
                }`}>{turn.text}</span>
              </div>
            ))}
          </div>

          {inSession && (
            <div className="p-3 px-4 border-t border-hairline flex gap-2">
              <input type="text" value={input} onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSend()}
                placeholder="Ask about past behaviour, not the future…"
                className="flex-1 h-10 px-3 border border-hairline rounded-lg bg-surface text-sm" aria-label="Message input" />
              <button onClick={handleSend} disabled={sendTurn.isPending || !input.trim()}
                className="h-10 px-4 rounded-lg border-none bg-accent text-white font-semibold disabled:opacity-50">Send</button>
            </div>
          )}

          {sessionResult && (
            <div className="p-3 px-4 border-t border-hairline flex items-center gap-2">
              {endedSessionId && (
                <Link to={`/conversations/${endedSessionId}`} className="text-sm text-accent hover:underline">View full conversation →</Link>
              )}
              <button onClick={() => { setSessionResult(null); setEndedSessionId(null); if (persona) createSession.mutate(persona.id); }}
                className="ml-auto h-9 px-4 rounded-lg border-none bg-accent text-white font-semibold">Start New Session</button>
            </div>
          )}
        </section>

        {/* ── Right: last / current score ── */}
        <section className="flex-[1_1_280px] max-w-[340px] bg-surface border border-hairline rounded-[10px] p-4 flex flex-col gap-2.5" aria-label="Last score">
          {shown ? (
            <>
              <span className="text-xs font-semibold text-muted">{shown.label}</span>
              <span className="text-4xl font-bold leading-none" style={{ color: scoreBand(shown.score).fg }}>
                {shown.score}/10
              </span>
              <span className="sr-only">Mom Test Score</span>
              {shown.good_questions.length > 0 && (
                <>
                  <span className="text-xs font-semibold text-good-text mt-1">Good questions</span>
                  <ul className="list-disc list-inside text-[13px] text-ink-2 m-0">
                    {shown.good_questions.map((q, i) => <li key={i}>{q}</li>)}
                  </ul>
                </>
              )}
              {shown.violations.length > 0 && (
                <>
                  <span className="text-xs font-semibold text-warn-text mt-1">To improve</span>
                  <ul className="flex flex-col gap-1.5 m-0 p-0 list-none">
                    {shown.violations.map((v, i) => (
                      <li key={i} className="text-[13px] text-ink-2"><span className="font-medium">{v.type}:</span> {v.better}</li>
                    ))}
                  </ul>
                </>
              )}
            </>
          ) : (
            <>
              <span className="text-xs font-semibold text-muted">Last score</span>
              <p className="text-sm text-muted">Finish a session with “End & Score” to see your Mom Test critique here.</p>
            </>
          )}
        </section>
      </div>
    </main>
  );
}
