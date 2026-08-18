import { useState } from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { api } from '../api';

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

  // Segment controls
  const [filterCompanyId, setFilterCompanyId] = useState<string>('');
  const [filterTag, setFilterTag] = useState<string>('');

  const { data: companies } = useQuery({
    queryKey: ['companies', 'active'],
    queryFn: () => api.listActiveCompanies(),
  });

  const { data: tags } = useQuery({
    queryKey: ['tags'],
    queryFn: () => api.listTags(),
  });

  // #19: Fetch past simulator sessions
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
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
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
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ persona_id: personaId }),
      });
      if (!r.ok) throw new Error('Failed to create session');
      return r.json() as Promise<{ id: number }>;
    },
    onSuccess: (data) => {
      setSessionId(data.id);
      setTurns([]);
      setSessionResult(null);
      setEndedSessionId(null);
    },
  });

  const sendTurn = useMutation({
    mutationFn: async (text: string) => {
      if (!sessionId) throw new Error('No session');
      const r = await fetch(`/api/simulator/sessions/${sessionId}/turns`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }),
      });
      if (!r.ok) throw new Error('Failed to send turn');
      return r.json() as Promise<{ reply: string }>;
    },
    onSuccess: (data, text) => {
      setTurns((prev) => [
        ...prev,
        { role: 'user', text },
        { role: 'persona', text: data.reply },
      ]);
      setInput('');
    },
  });

  const endSession = useMutation({
    mutationFn: async () => {
      if (!sessionId) throw new Error('No session');
      const r = await fetch(`/api/simulator/sessions/${sessionId}/end`, { method: 'POST' });
      if (!r.ok) {
        const err = await r.json().catch(() => ({ detail: 'Failed' }));
        throw new Error(err.detail || 'Failed to end session');
      }
      return r.json();
    },
    onSuccess: () => {
      const sid = sessionId!;
      setEndedSessionId(sid);
      setSessionId(null);
      setIsPolling(true);
      // Poll for result
      pollForResult(sid);
    },
  });

  const pollForResult = async (sid: number) => {
    const maxAttempts = 15;
    for (let i = 0; i < maxAttempts; i++) {
      try {
        const r = await fetch(`/api/simulator/sessions/${sid}/result`);
        if (r.ok) {
          const data: SessionResult = await r.json();
          if (data.analysis?.result) {
            setSessionResult(data);
            setIsPolling(false);
            return;
          }
        }
      } catch {
        // ignore and retry
      }
      await new Promise((resolve) => setTimeout(resolve, 2000));
    }
    // Timeout: show partial result
    try {
      const r = await fetch(`/api/simulator/sessions/${sid}/result`);
      if (r.ok) {
        setSessionResult(await r.json());
      }
    } catch { /* ignore */ }
    setIsPolling(false);
  };

  const handleSend = () => {
    if (!input.trim()) return;
    sendTurn.mutate(input.trim());
  };

  // Phase 1: Build/select persona
  if (!persona) {
    return (
      <div className="max-w-2xl mx-auto p-6">
        <h1 className="text-xl font-bold tracking-tight mb-4">🎯 Interview Flight Simulator</h1>
        <p className="text-sm text-muted mb-6">
          Practice your interview skills with an AI persona built from your evidence corpus.
        </p>

        <div className="bg-surface rounded-xl border border-hairline p-4 mb-4">
          <h2 className="font-semibold mb-2 text-ink-2">Build persona from segment</h2>
          <p className="text-sm text-muted mb-3">
            Leave empty for a canned starter persona, or filter by company/tag.
          </p>

          <div className="grid grid-cols-2 gap-3 mb-4">
            <div>
              <label htmlFor="sim-company" className="text-xs font-medium text-muted block mb-1">Company</label>
              <select
                id="sim-company"
                value={filterCompanyId}
                onChange={(e) => setFilterCompanyId(e.target.value)}
                className="w-full border border-hairline rounded-lg px-3 py-2 text-sm bg-page text-ink-2"
                aria-label="Simulator persona company filter"
              >
                <option value="">All companies</option>
                {companies?.map((c) => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="sim-tag" className="text-xs font-medium text-muted block mb-1">Tag</label>
              <select
                id="sim-tag"
                value={filterTag}
                onChange={(e) => setFilterTag(e.target.value)}
                className="w-full border border-hairline rounded-lg px-3 py-2 text-sm bg-page text-ink-2"
              >
                <option value="">All tags</option>
                {tags?.map((t) => (
                  <option key={t.key} value={t.key}>{t.emoji} {t.name}</option>
                ))}
              </select>
            </div>
          </div>

          <button
            onClick={() => buildPersona.mutate()}
            disabled={buildPersona.isPending}
            className="btn btn-primary"
          >
            {buildPersona.isPending ? 'Building...' : 'Build Persona'}
          </button>
        </div>

        {/* #19: Past practice sessions */}
        <div className="bg-surface rounded-xl border border-hairline p-4" data-testid="past-sessions">
          <h2 className="font-semibold mb-3 text-ink-2">Past practice sessions</h2>
          {sessionsLoading && (
            <p className="text-sm text-muted">Loading sessions…</p>
          )}
          {sessionsError && (
            <p className="text-sm text-crit" role="alert">Failed to load past sessions.</p>
          )}
          {!sessionsLoading && !sessionsError && pastSessions && pastSessions.items.length === 0 && (
            <p className="text-sm text-muted" data-testid="no-past-sessions">No practice sessions yet. Build a persona and start practicing!</p>
          )}
          {!sessionsLoading && pastSessions && pastSessions.items.length > 0 && (
            <div className="space-y-2">
              {pastSessions.items.map((s: PastSession) => (
                <Link
                  key={s.id}
                  to={`/conversations/${s.id}`}
                  className="flex items-center justify-between p-3 rounded-lg border border-hairline hover:border-accent transition-colors"
                  data-testid="past-session-item"
                >
                  <div>
                    <span className="text-sm font-medium text-ink-2">{s.title}</span>
                    {s.created_at && (
                      <span className="text-xs text-muted ml-2">
                        {new Date(s.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    <span className={`text-xs px-2 py-0.5 rounded-full ${
                      s.status === 'ready' ? 'bg-[#e6f4e6] text-good-text' :
                      s.status === 'failed' ? 'bg-[#fbe7e7] text-crit' :
                      'bg-page text-muted'
                    }`}>
                      {s.status}
                    </span>
                    {s.score != null && (
                      <span className="text-sm font-bold text-accent">{s.score}/10</span>
                    )}
                  </div>
                </Link>
              ))}
            </div>
          )}
        </div>
      </div>
    );
  }

  // Phase 2: Start session
  if (!sessionId && !sessionResult && !isPolling) {
    const p = persona.result;
    return (
      <div className="max-w-2xl mx-auto p-6">
        <h1 className="text-xl font-bold tracking-tight mb-4">🎯 Interview Flight Simulator</h1>

        <div className="bg-surface rounded-xl border border-hairline p-4 mb-4">
          <h2 className="font-semibold text-lg text-ink-2">{p.name}</h2>
          <p className="text-muted">{p.role} — {p.company_profile}</p>
          {p.sore_points.length > 0 && (
            <div className="mt-2">
              <span className="text-sm font-medium">Sore points:</span>
              <ul className="list-disc list-inside text-sm text-muted">
                {p.sore_points.map((sp, i) => <li key={i}>{sp}</li>)}
              </ul>
            </div>
          )}
        </div>

        <button
          onClick={() => createSession.mutate(persona.id)}
          disabled={createSession.isPending}
          className="px-4 py-2 bg-good text-white rounded-lg font-semibold hover:bg-good/90 disabled:opacity-50"
        >
          {createSession.isPending ? 'Starting...' : 'Start Session'}
        </button>
        <button
          onClick={() => setPersona(null)}
          className="ml-2 px-4 py-2 bg-page border border-hairline rounded-lg text-ink-2 hover:bg-surface"
        >
          Choose Different Persona
        </button>
      </div>
    );
  }

  // Phase 3: Chat / scoring / result display
  return (
    <div className="max-w-2xl mx-auto p-6">
      <h1 className="text-xl font-bold tracking-tight mb-4">🎯 Interview Flight Simulator</h1>

      {/* Show session link if we have an ended session */}
      {endedSessionId && (
        <div className="text-sm text-muted mb-2">
          Session ID: <Link to={`/conversations/${endedSessionId}`} className="text-accent hover:underline">#{endedSessionId}</Link>
        </div>
      )}

      {isPolling && (
        <div className="bg-surface rounded-xl border border-hairline p-4">
          <h2 className="font-semibold text-lg text-ink-2 mb-2">Session Complete</h2>
          <p className="text-muted" role="status">Scoring your interview... This may take a moment.</p>
          <div className="mt-2 flex items-center gap-2">
            <span className="w-4 h-4 border-2 border-hairline border-t-accent rounded-full animate-spin" aria-hidden="true" />
            <span className="text-sm text-muted">Waiting for critique...</span>
          </div>
        </div>
      )}

      {sessionResult && (
        <div className="bg-surface rounded-xl border border-hairline p-4">
          <h2 className="font-semibold text-lg text-ink-2 mb-2">Session Complete</h2>

          {sessionResult.analysis?.result?.mom_test_critique ? (
            <div>
              <div className="flex items-center gap-3 mb-3">
                <span className="text-3xl font-bold text-accent">
                  {sessionResult.analysis.result.mom_test_critique.score}/10
                </span>
                <span className="text-muted">Mom Test Score</span>
              </div>

              {sessionResult.analysis.result.mom_test_critique.good_questions.length > 0 && (
                <div className="mb-3">
                  <h3 className="text-sm font-semibold text-good-text mb-1">✓ Good questions</h3>
                  <ul className="list-disc list-inside text-sm text-ink-2">
                    {sessionResult.analysis.result.mom_test_critique.good_questions.map((q, i) => (
                      <li key={i}>{q}</li>
                    ))}
                  </ul>
                </div>
              )}

              {sessionResult.analysis.result.mom_test_critique.violations.length > 0 && (
                <div className="mb-3">
                  <h3 className="text-sm font-semibold text-crit mb-1">✗ Violations</h3>
                  <ul className="space-y-1">
                    {sessionResult.analysis.result.mom_test_critique.violations.map((v, i) => (
                      <li key={i} className="text-sm text-ink-2">
                        <span className="font-medium">{v.type}</span>: {v.better}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          ) : (
            <p className="text-muted">
              {sessionResult.analysis ? 'Analysis complete.' : 'Analysis not yet available.'}
            </p>
          )}

          {endedSessionId && (
            <Link
              to={`/conversations/${endedSessionId}`}
              className="inline-block mt-3 text-sm text-accent hover:underline"
            >
              View full conversation →
            </Link>
          )}

          <button
            onClick={() => { setPersona(null); setSessionResult(null); setEndedSessionId(null); }}
            className="mt-4 ml-3 btn btn-primary"
          >
            Start New Session
          </button>
        </div>
      )}

      {sessionId && !isPolling && !sessionResult && (
        <>
          <div className="bg-surface rounded-xl border border-hairline p-4 mb-4 max-h-96 overflow-y-auto" role="log" aria-label="Conversation">
            {turns.length === 0 && (
              <p className="text-muted italic">Start the conversation. Ask about their past experiences.</p>
            )}
            {turns.map((turn, i) => (
              <div
                key={i}
                className={`mb-3 ${turn.role === 'user' ? 'text-right' : 'text-left'}`}
              >
                <span className={`inline-block px-3 py-2 rounded-lg text-sm ${
                  turn.role === 'user'
                    ? 'bg-accent-soft text-accent'
                    : 'bg-page text-ink-2'
                }`}>
                  {turn.text}
                </span>
              </div>
            ))}
          </div>

          <div className="flex gap-2">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSend()}
              placeholder="Ask a question..."
              className="flex-1 border border-hairline rounded-lg px-3 py-2 bg-page"
              aria-label="Message input"
            />
            <button
              onClick={handleSend}
              disabled={sendTurn.isPending || !input.trim()}
              className="btn btn-primary"
            >
              Send
            </button>
            <button
              onClick={() => endSession.mutate()}
              disabled={endSession.isPending || turns.length === 0}
              className="px-4 py-2 bg-crit text-white rounded-lg font-semibold hover:bg-crit/90 disabled:opacity-50"
            >
              End & Score
            </button>
          </div>
        </>
      )}
    </div>
  );
}
