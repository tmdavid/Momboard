import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

interface BotResponse {
  platform: string;
  native_meeting_id: string;
  status: string;
}

interface TranscriptResponse {
  segments: { speaker: string; text: string; completed: boolean }[];
  total: number;
}

interface SessionHistoryEntry {
  id: number;
  platform: string;
  meeting_id: string;
  status: 'active' | 'completed' | 'stopped' | 'imported';
  started_at: string;
  note?: string;
}

export function MeetingsPage() {
  const queryClient = useQueryClient();
  const [meetingUrl, setMeetingUrl] = useState('');
  const [activeBot, setActiveBot] = useState<{ platform: string; native_meeting_id: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sessionHistory, setSessionHistory] = useState<SessionHistoryEntry[]>([]);

  const sendBot = useMutation({
    mutationFn: async (url: string) => {
      const r = await fetch('/api/vexa/bots', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ meeting_url: url }),
      });
      if (!r.ok) {
        const err = await r.json();
        throw new Error(err.detail || `Error ${r.status}`);
      }
      return r.json() as Promise<BotResponse>;
    },
    onSuccess: (data) => {
      setActiveBot({ platform: data.platform, native_meeting_id: data.native_meeting_id });
      setMeetingUrl('');
      setError(null);
      // Append active entry to session history
      setSessionHistory((prev) => [
        ...prev,
        {
          id: prev.length + 1,
          platform: data.platform,
          meeting_id: data.native_meeting_id,
          status: 'active',
          started_at: new Date().toISOString(),
        },
      ]);
    },
    onError: (err) => setError((err as Error).message),
  });

  const { data: transcript } = useQuery({
    queryKey: ['vexa-transcript', activeBot?.platform, activeBot?.native_meeting_id],
    queryFn: async () => {
      if (!activeBot) return { segments: [], total: 0 };
      const r = await fetch(`/api/vexa/transcripts/${activeBot.platform}/${activeBot.native_meeting_id}`);
      if (!r.ok) return { segments: [], total: 0 };
      return r.json() as Promise<TranscriptResponse>;
    },
    enabled: !!activeBot,
    refetchInterval: 10000,
  });

  const stopBot = useMutation({
    mutationFn: async () => {
      if (!activeBot) return;
      const r = await fetch(`/api/vexa/bots/${activeBot.platform}/${activeBot.native_meeting_id}`, { method: 'DELETE' });
      if (!r.ok) throw new Error('Failed to stop');
      return r.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['vexa-transcript', activeBot?.platform, activeBot?.native_meeting_id] });
      // Update session history: mark current bot as stopped
      setSessionHistory((prev) =>
        prev.map((entry) =>
          entry.platform === activeBot?.platform && entry.meeting_id === activeBot?.native_meeting_id && entry.status === 'active'
            ? { ...entry, status: 'stopped' as const }
            : entry,
        ),
      );
    },
  });

  const importTranscript = useMutation({
    mutationFn: async () => {
      if (!activeBot) return;
      const r = await fetch('/api/vexa/import', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          platform: activeBot.platform,
          native_meeting_id: activeBot.native_meeting_id,
        }),
      });
      if (!r.ok) {
        const err = await r.json();
        throw new Error(err.detail || 'Failed to import');
      }
      return r.json();
    },
    onSuccess: () => {
      setError(null);
      // Update session history: mark as imported
      setSessionHistory((prev) =>
        prev.map((entry) =>
          entry.platform === activeBot?.platform && entry.meeting_id === activeBot?.native_meeting_id
            ? { ...entry, status: 'imported' as const, note: 'Available in Library > Inbox' }
            : entry,
        ),
      );
    },
    onError: (err) => setError((err as Error).message),
  });

  return (
    <div className="max-w-3xl mx-auto p-6">
      <h1 className="text-xl font-bold tracking-tight mb-2">Meeting Bots</h1>
      <p className="text-sm text-muted mb-6">
        Send a bot to record and transcribe your meetings. Completed transcripts import to Library &gt; Inbox.
      </p>
      <div className="bg-accent-soft border border-hairline rounded-xl px-4 py-3 mb-6 text-[13px] text-ink-2">
        <b>Consent reminder:</b> Ensure all meeting participants consent to recording before sending a bot.
      </div>

      {/* Send bot form */}
      <div className="bg-surface rounded-xl border border-hairline p-4 mb-6">
        <h2 className="font-semibold mb-2 text-ink-2">Send bot to meeting</h2>
        <div className="flex gap-2">
          <input
            type="text"
            value={meetingUrl}
            onChange={(e) => setMeetingUrl(e.target.value)}
            placeholder="Meeting URL (Google Meet, Zoom, Teams, Jitsi)"
            className="flex-1 border border-hairline rounded-lg px-3 py-2 bg-page"
            aria-label="Meeting URL"
          />
          <button
            onClick={() => sendBot.mutate(meetingUrl)}
            disabled={!meetingUrl.trim() || sendBot.isPending}
            className="btn btn-primary"
          >
            {sendBot.isPending ? 'Sending...' : 'Send Bot'}
          </button>
        </div>
        {error && <p className="text-crit text-sm mt-2" role="alert">{error}</p>}
      </div>

      {/* Active bot panel */}
      {activeBot && (
        <div className="bg-surface rounded-xl border border-hairline p-4 mb-6">
          <div className="flex items-center justify-between mb-3">
            <h2 className="font-semibold text-ink-2">
              Meeting: {activeBot.platform}/{activeBot.native_meeting_id}
            </h2>
          </div>

          <div className="flex gap-2 mb-4">
            <button
              onClick={() => stopBot.mutate()}
              disabled={stopBot.isPending}
              className="px-3 py-1.5 bg-crit text-white text-sm rounded-lg hover:bg-crit/90 disabled:opacity-50"
            >
              Stop Bot
            </button>
            <button
              onClick={() => importTranscript.mutate()}
              disabled={importTranscript.isPending || !transcript?.total}
              className="px-3 py-1.5 bg-good text-white text-sm rounded-lg hover:bg-good/90 disabled:opacity-50"
            >
              Import to Inbox
            </button>
          </div>

          {/* Transcript preview */}
          {transcript && transcript.segments.length > 0 && (
            <div className="border border-hairline rounded-lg p-3 max-h-60 overflow-y-auto bg-page">
              <h3 className="text-sm font-medium mb-2 text-ink-2">Preview ({transcript.total} segments)</h3>
              {transcript.segments.map((seg, i) => (
                <p key={i} className="text-sm mb-1 text-ink-2">
                  <span className="font-medium">{seg.speaker}:</span> {seg.text}
                </p>
              ))}
            </div>
          )}
        </div>
      )}

      {/* #18: This session history */}
      <div className="bg-surface rounded-xl border border-hairline p-4" data-testid="session-history">
        <h2 className="font-semibold mb-2 text-ink-2">This session history</h2>
        <p className="text-xs text-muted mb-3">Session-only — resets on page reload.</p>
        {sessionHistory.length === 0 ? (
          <p className="text-sm text-muted py-4 text-center" data-testid="session-history-empty">
            No bots sent yet in this session.
          </p>
        ) : (
          <table className="w-full text-sm" role="table" aria-label="Session history">
            <thead>
              <tr className="text-left text-xs text-muted uppercase tracking-wider border-b border-hairline">
                <th className="pb-2 pr-3">Meeting</th>
                <th className="pb-2 pr-3">Started</th>
                <th className="pb-2">Status</th>
              </tr>
            </thead>
            <tbody>
              {sessionHistory.map((entry) => (
                <tr key={entry.id} className="border-b border-hairline last:border-b-0" data-testid="session-history-row">
                  <td className="py-2 pr-3 text-ink-2">
                    {entry.meeting_id}
                  </td>
                  <td className="py-2 pr-3 text-muted">
                    {new Date(entry.started_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                  </td>
                  <td className="py-2">
                    <span
                      className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full ${
                        entry.status === 'active' ? 'bg-accent-soft text-accent' :
                        entry.status === 'completed' || entry.status === 'stopped' ? 'bg-page text-muted' :
                        entry.status === 'imported' ? 'bg-[#e6f4e6] text-good-text' :
                        'bg-page text-muted'
                      }`}
                      role="status"
                      aria-label={`Bot status: ${entry.status}`}
                    >
                      {entry.status === 'active' && <span className="w-2 h-2 border border-accent border-t-transparent rounded-full animate-spin" aria-hidden="true" />}
                      {entry.status}
                    </span>
                    {entry.note && (
                      <span className="ml-2 text-xs text-muted">{entry.note}</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
