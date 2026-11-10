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
  const all = tags ?? [];

  // Data-driven grouping for tag menus: "Core" first, then one group per custom
  // category (alphabetical), then "Other" for uncategorized custom tags. Adding a
  // new category requires no code change — it appears here as soon as a tag uses it.
  const groups: { label: string; tags: Tag[] }[] = [];
  const core = all.filter((t) => t.origin === 'core');
  if (core.length) groups.push({ label: 'Core', tags: core });

  const custom = all.filter((t) => t.origin !== 'core');
  const categories = Array.from(
    new Set(custom.map((t) => t.category).filter((c): c is string => !!c)),
  ).sort((a, b) => a.localeCompare(b));
  for (const cat of categories) {
    groups.push({ label: cat, tags: custom.filter((t) => t.category === cat) });
  }
  const uncategorized = custom.filter((t) => !t.category);
  if (uncategorized.length) groups.push({ label: 'Other', tags: uncategorized });

  return {
    tags: all,
    groups,
    emoji: (key: string): string => byKey.get(key)?.emoji ?? fallbackEmoji(key),
    name: (key: string): string => byKey.get(key)?.name ?? fallbackName(key),
  };
}
