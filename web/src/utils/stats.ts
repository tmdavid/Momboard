/** Small derivations over /api/stats, shared so two pages can never disagree about a number. */

type MonthlyTagCounts = Record<string, Record<string, number>> | undefined | null;

/** Total highlights per tag across every month, e.g. { pain: 1500 }. */
export function totalsByTag(byMonth: MonthlyTagCounts): Record<string, number> {
  const totals: Record<string, number> = {};
  for (const month of Object.values(byMonth ?? {})) {
    for (const [tag, n] of Object.entries(month ?? {})) totals[tag] = (totals[tag] ?? 0) + (Number(n) || 0);
  }
  return totals;
}
