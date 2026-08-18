import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';

type InboxStatus = 'pending_import' | 'parse_error' | 'imported' | 'ignored';

interface InboxItem {
  id: number;
  source: string;
  source_ref: string;
  title: string;
  status: InboxStatus;
  parse_error: string | null;
  created_at: string;
  conversation_id: number | null;
}

export function InboxPage() {
  return <InboxPane />;
}

/**
 * InboxPane — the actual inbox content, usable both as a standalone page
 * and embedded as a Library subtab (#nav-redesign).
 */
export function InboxPane() {
  const [statusFilter, setStatusFilter] = useState<InboxStatus | ''>('pending_import');
  const queryClient = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: ['inbox', statusFilter],
    queryFn: async () => {
      const params = new URLSearchParams();
      if (statusFilter) params.set('status', statusFilter);
      const res = await fetch(`/api/inbox?${params}`, { credentials: 'include' });
      if (!res.ok) throw new Error('Failed to fetch inbox');
      return res.json() as Promise<{ items: InboxItem[]; total: number }>;
    },
  });

  const importMutation = useMutation({
    mutationFn: async (itemId: number) => {
      const res = await fetch(`/api/inbox/${itemId}/import`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      if (!res.ok) throw new Error('Import failed');
      return res.json();
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['inbox'] }),
  });

  const ignoreMutation = useMutation({
    mutationFn: async (itemId: number) => {
      const res = await fetch(`/api/inbox/${itemId}/ignore`, {
        method: 'POST',
        credentials: 'include',
      });
      if (!res.ok) throw new Error('Ignore failed');
      return res.json();
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['inbox'] }),
  });

  const statusTabs: { value: InboxStatus | ''; label: string }[] = [
    { value: 'pending_import', label: 'Pending' },
    { value: 'parse_error', label: 'Parse Errors' },
    { value: 'imported', label: 'Imported' },
    { value: 'ignored', label: 'Ignored' },
    { value: '', label: 'All' },
  ];

  return (
    <div className="max-w-5xl mx-auto p-6">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-semibold">Inbox</h1>
        <span className="text-sm text-gray-500">
          {data?.total ?? 0} items
        </span>
      </div>

      {/* Status filter tabs */}
      <div className="flex gap-1 mb-4 border-b" role="tablist">
        {statusTabs.map((tab) => (
          <button
            key={tab.value}
            role="tab"
            aria-selected={statusFilter === tab.value}
            className={`px-4 py-2 text-sm rounded-t transition-colors ${
              statusFilter === tab.value
                ? 'bg-white border border-b-white text-indigo-600 font-medium -mb-px'
                : 'text-gray-500 hover:text-gray-700'
            }`}
            onClick={() => setStatusFilter(tab.value as InboxStatus | '')}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Items list */}
      {isLoading ? (
        <div className="text-center py-8 text-gray-400">Loading...</div>
      ) : !data?.items?.length ? (
        <div className="text-center py-8 text-gray-400">No items</div>
      ) : (
        <ul className="divide-y" role="list">
          {data.items.map((item) => (
            <li key={item.id} className="py-4 flex items-start gap-4">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-medium truncate">{item.title}</span>
                  <StatusBadge status={item.status} />
                  <SourceBadge source={item.source} />
                </div>
                <p className="text-xs text-gray-400 mt-1">
                  {item.source_ref} · {new Date(item.created_at).toLocaleDateString()}
                </p>
                {item.parse_error && (
                  <p className="text-xs text-red-500 mt-1" data-testid="parse-error">
                    ⚠️ {item.parse_error}
                  </p>
                )}
              </div>
              <div className="flex gap-2 shrink-0">
                {(item.status === 'pending_import' || item.status === 'parse_error') && (
                  <>
                    <button
                      className="px-3 py-1 text-sm bg-indigo-600 text-white rounded hover:bg-indigo-700"
                      onClick={() => importMutation.mutate(item.id)}
                      disabled={importMutation.isPending}
                    >
                      Import
                    </button>
                    <button
                      className="px-3 py-1 text-sm border border-gray-300 rounded hover:bg-gray-50"
                      onClick={() => ignoreMutation.mutate(item.id)}
                      disabled={ignoreMutation.isPending}
                    >
                      Ignore
                    </button>
                  </>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    pending_import: 'bg-yellow-100 text-yellow-800',
    parse_error: 'bg-red-100 text-red-800',
    imported: 'bg-green-100 text-green-800',
    ignored: 'bg-gray-100 text-gray-600',
  };
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full ${colors[status] ?? 'bg-gray-100'}`}>
      {status.replace('_', ' ')}
    </span>
  );
}

function SourceBadge({ source }: { source: string }) {
  return (
    <span className="text-xs px-2 py-0.5 rounded bg-blue-50 text-blue-600">
      {source}
    </span>
  );
}
