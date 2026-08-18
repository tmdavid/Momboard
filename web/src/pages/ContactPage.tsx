import { useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';

type KindFilter = '' | 'conversations' | 'signals' | 'commitments';

interface TimelineEvent {
  kind: string;
  timestamp: string;
  conversation_id?: number;
  title?: string;
  highlight_id?: number;
  tag_key?: string;
  tag_emoji?: string;
  quote?: string;
  status?: string;
}

interface ContactDetail {
  id: number;
  name: string;
  role: string | null;
  company_id: number | null;
  company_name: string | null;
  stats: {
    conversation_count: number;
    open_followups: number;
    last_talked: string | null;
  };
}

interface DriftAlert {
  id: number;
  kind: string;
  summary: string;
  status: string;
  earlier_quote: string;
  later_quote: string;
}

export function ContactPage() {
  const { id } = useParams<{ id: string }>();
  const [kindFilter, setKindFilter] = useState<KindFilter>('');
  const queryClient = useQueryClient();

  const { data: contact, isLoading: contactLoading } = useQuery({
    queryKey: ['contact', id],
    queryFn: async () => {
      const res = await fetch(`/api/contacts/${id}`, { credentials: 'include' });
      if (!res.ok) throw new Error('Not found');
      return res.json() as Promise<ContactDetail>;
    },
  });

  const { data: timeline } = useQuery({
    queryKey: ['contact-timeline', id, kindFilter],
    queryFn: async () => {
      const params = new URLSearchParams();
      if (kindFilter) params.set('kind', kindFilter);
      const res = await fetch(`/api/contacts/${id}/timeline?${params}`, { credentials: 'include' });
      if (!res.ok) return [];
      return res.json() as Promise<TimelineEvent[]>;
    },
    enabled: !!id,
  });

  const { data: drifts } = useQuery({
    queryKey: ['contact-drifts', id],
    queryFn: async () => {
      const res = await fetch(`/api/contacts/${id}/drifts`, { credentials: 'include' });
      if (!res.ok) return [];
      return res.json() as Promise<DriftAlert[]>;
    },
    enabled: !!id,
  });

  const dismissDrift = useMutation({
    mutationFn: async (driftId: number) => {
      await fetch(`/api/drifts/${driftId}/dismiss`, { method: 'POST', credentials: 'include' });
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['contact-drifts'] }),
  });

  const confirmDrift = useMutation({
    mutationFn: async (driftId: number) => {
      await fetch(`/api/drifts/${driftId}/confirm`, { method: 'POST', credentials: 'include' });
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['contact-drifts'] }),
  });

  // Brief button
  const briefMutation = useMutation({
    mutationFn: async () => {
      const res = await fetch(`/api/contacts/${id}/brief`, { credentials: 'include' });
      if (!res.ok) throw new Error('Failed to generate brief');
      return res.json();
    },
  });

  if (contactLoading) return <div className="p-6 text-gray-400">Loading...</div>;
  if (!contact) return <div className="p-6">Contact not found</div>;

  return (
    <div className="max-w-4xl mx-auto p-6">
      {/* Header with stats */}
      <header className="mb-6">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-semibold">{contact.name}</h1>
          {contact.role && <span className="text-gray-500">{contact.role}</span>}
        </div>
        {contact.company_name && (
          <Link
            to={`/companies/${contact.company_id}`}
            className="text-indigo-600 hover:underline text-sm"
          >
            {contact.company_name}
          </Link>
        )}
        <div className="flex gap-6 mt-3 text-sm text-gray-500">
          <span>{contact.stats.conversation_count} conversations</span>
          <span>{contact.stats.open_followups} open follow-ups</span>
          <span>Last: {contact.stats.last_talked ?? 'Never'}</span>
        </div>
        <button
          className="mt-3 px-4 py-2 bg-indigo-600 text-white rounded text-sm hover:bg-indigo-700"
          onClick={() => briefMutation.mutate()}
          disabled={briefMutation.isPending}
          data-testid="prep-brief-btn"
        >
          {briefMutation.isPending ? 'Generating...' : '📋 Prep Brief'}
        </button>

        {/* Brief result */}
        {briefMutation.data && (
          <div className="mt-4 p-4 bg-gray-50 rounded border print:border-none" data-testid="brief-result">
            <h3 className="font-medium mb-2">Pre-call Brief</h3>
            {briefMutation.data.suggested_questions?.length > 0 && (
              <div>
                <h4 className="text-sm font-medium text-gray-600">Suggested Questions:</h4>
                <ul className="list-disc list-inside text-sm">
                  {briefMutation.data.suggested_questions.map((q: string, i: number) => (
                    <li key={i}>{q}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </header>

      {/* Drift alerts */}
      {drifts && drifts.length > 0 && (
        <section className="mb-6" aria-label="Drift alerts">
          <h2 className="text-lg font-medium mb-2">🔄 Drift Alerts</h2>
          {drifts.map((drift) => (
            <div key={drift.id} className="border rounded p-4 mb-3 bg-amber-50">
              <div className="flex gap-4 mb-2">
                <div className="flex-1">
                  <p className="text-xs text-gray-500 mb-1">Earlier:</p>
                  <blockquote className="text-sm italic">"{drift.earlier_quote}"</blockquote>
                </div>
                <div className="flex-1">
                  <p className="text-xs text-gray-500 mb-1">Now:</p>
                  <blockquote className="text-sm italic">"{drift.later_quote}"</blockquote>
                </div>
              </div>
              <p className="text-sm text-gray-700">{drift.summary}</p>
              <div className="flex gap-2 mt-2">
                <button
                  className="text-xs px-2 py-1 border rounded hover:bg-white"
                  onClick={() => dismissDrift.mutate(drift.id)}
                >
                  Dismiss
                </button>
                <button
                  className="text-xs px-2 py-1 border rounded hover:bg-white"
                  onClick={() => confirmDrift.mutate(drift.id)}
                >
                  Confirm
                </button>
              </div>
            </div>
          ))}
        </section>
      )}

      {/* Kind filter */}
      <div className="flex gap-2 mb-4">
        {(['', 'conversations', 'signals', 'commitments'] as KindFilter[]).map((kind) => (
          <button
            key={kind}
            className={`px-3 py-1 text-sm rounded ${
              kindFilter === kind ? 'bg-indigo-100 text-indigo-700' : 'bg-gray-100 text-gray-600'
            }`}
            onClick={() => setKindFilter(kind)}
          >
            {kind || 'All'}
          </button>
        ))}
      </div>

      {/* Timeline (newest-first) */}
      <section aria-label="Timeline">
        {!timeline?.length ? (
          <p className="text-gray-400 text-sm">No events yet</p>
        ) : (
          <ul className="space-y-3">
            {timeline.map((event, i) => (
              <li key={i} className="flex gap-3 items-start">
                <KindIcon kind={event.kind} emoji={event.tag_emoji} />
                <div className="flex-1 min-w-0">
                  {event.kind === 'conversation' && (
                    <Link
                      to={`/conversations/${event.conversation_id}`}
                      className="text-sm text-indigo-600 hover:underline"
                    >
                      {event.title}
                    </Link>
                  )}
                  {(event.kind === 'highlight' || event.kind === 'commitment') && (
                    <p className="text-sm">
                      <span className="text-gray-500">{event.tag_emoji}</span>{' '}
                      "{event.quote}"
                    </p>
                  )}
                  <time className="text-xs text-gray-400">
                    {new Date(event.timestamp).toLocaleDateString()}
                  </time>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function KindIcon({ kind, emoji }: { kind: string; emoji?: string }) {
  const icons: Record<string, string> = {
    conversation: '💬',
    highlight: emoji || '📌',
    commitment: '🤝',
  };
  return <span className="text-lg">{icons[kind] || '•'}</span>;
}
