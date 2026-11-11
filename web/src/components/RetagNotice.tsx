import { useQuery } from '@tanstack/react-query';
import { api } from '../api';
import { formatNumber } from '../utils/format';

/**
 * "Impersonation was added after 688 calls were tagged. Retag them to include them." (v0.5 D7)
 *
 * Filtering by a tag that older calls never saw would otherwise return fewer results than the truth
 * and say nothing. Renders nothing unless a filtered tag is missing from at least one call.
 */
export function RetagNotice({ tagKeys }: { tagKeys: string[] }) {
  const keys = [...tagKeys].sort();
  const { data } = useQuery({
    queryKey: ['taxonomy-stale', keys],
    queryFn: () => api.taxonomyStale(keys),
    enabled: keys.length > 0,
    staleTime: 60_000,
  });
  const missing = (data?.items ?? []).filter((t) => t.stale_calls > 0);
  if (missing.length === 0) return null;
  return (
    <div role="note" data-testid="retag-notice" className="text-sm text-ink-2 bg-page border border-hairline rounded-lg px-3 py-2">
      {missing.map((t) => (
        <p key={t.key} className="m-0">
          {t.name} was added after {formatNumber(t.stale_calls)} calls were tagged. Retag them to include them.
        </p>
      ))}
    </div>
  );
}
