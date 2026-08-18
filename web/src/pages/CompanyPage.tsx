import { useParams, Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';

interface CompanyDetail {
  id: number;
  name: string;
  domain: string | null;
  contacts: { id: number; name: string; role: string | null }[];
}

interface TimelineEvent {
  kind: string;
  timestamp: string;
  conversation_id?: number;
  title?: string;
  highlight_id?: number;
  tag_key?: string;
  quote?: string;
}

export function CompanyPage() {
  const { id } = useParams<{ id: string }>();

  const { data: company, isLoading } = useQuery({
    queryKey: ['company', id],
    queryFn: async () => {
      const res = await fetch(`/api/companies/${id}`, { credentials: 'include' });
      if (!res.ok) throw new Error('Not found');
      return res.json() as Promise<CompanyDetail>;
    },
  });

  const { data: timeline } = useQuery({
    queryKey: ['company-timeline', id],
    queryFn: async () => {
      const res = await fetch(`/api/companies/${id}/timeline`, { credentials: 'include' });
      if (!res.ok) return [];
      return res.json() as Promise<TimelineEvent[]>;
    },
    enabled: !!id,
  });

  if (isLoading) return <div className="p-6 text-gray-400">Loading...</div>;
  if (!company) return <div className="p-6">Company not found</div>;

  return (
    <div className="max-w-4xl mx-auto p-6">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold">{company.name}</h1>
        {company.domain && <p className="text-sm text-gray-500">{company.domain}</p>}
      </header>

      {/* Grouped contacts */}
      {company.contacts?.length > 0 && (
        <section className="mb-6">
          <h2 className="text-lg font-medium mb-2">Contacts</h2>
          <ul className="divide-y">
            {company.contacts.map((c) => (
              <li key={c.id} className="py-2">
                <Link to={`/contacts/${c.id}`} className="text-indigo-600 hover:underline">
                  {c.name}
                </Link>
                {c.role && <span className="text-sm text-gray-500 ml-2">{c.role}</span>}
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* Timeline */}
      <section aria-label="Company timeline">
        <h2 className="text-lg font-medium mb-2">Timeline</h2>
        {!timeline?.length ? (
          <p className="text-gray-400 text-sm">No events</p>
        ) : (
          <ul className="space-y-3">
            {timeline.map((event, i) => (
              <li key={i} className="flex gap-3 items-start text-sm">
                <span>{event.kind === 'conversation' ? '💬' : '📌'}</span>
                <div className="flex-1">
                  {event.kind === 'conversation' ? (
                    <Link
                      to={`/conversations/${event.conversation_id}`}
                      className="text-indigo-600 hover:underline"
                    >
                      {event.title}
                    </Link>
                  ) : (
                    <p>"{event.quote}"</p>
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
