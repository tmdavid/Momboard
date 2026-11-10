import { useQuery } from '@tanstack/react-query';
import { api, Tag } from '../api';
import { tagEmoji as fallbackEmoji, tagName as fallbackName } from '../constants';

/**
 * Live taxonomy lookup. Tags are user-extensible (custom tags created via
 * /api/tags), so emoji/name must come from the DB, not the hardcoded TAG_META
 * constant — otherwise custom tags render a '?' icon and their raw key as the name.
 *
 * Reuses the shared ['tags'] react-query cache (already populated by Settings /
 * Explore / Simulator), so this is effectively free. Falls back to the built-in
 * TAG_META for the seed tags while the fetch is in flight, so nothing flickers to
 * '?' on first paint.
 */
export function useTaxonomy() {
  const { data: tags } = useQuery({
    queryKey: ['tags'],
    queryFn: () => api.listTags(),
    staleTime: 5 * 60 * 1000,
  });

  const byKey = new Map<string, Tag>((tags ?? []).map((t) => [t.key, t]));

  return {
    tags: tags ?? [],
    emoji: (key: string): string => byKey.get(key)?.emoji ?? fallbackEmoji(key),
    name: (key: string): string => byKey.get(key)?.name ?? fallbackName(key),
  };
}
