/**
 * One place for how numbers and dates look (v0.5 U9).
 *
 * Numbers get thousands separators ("1,000"). Dates read "14 Sep 2026", never a raw ISO string
 * ("2026-09-14T12:30:00"). Anything missing or unparseable renders as "—", never "NaN" or
 * "Invalid Date". The locale is fixed on purpose so the app reads the same on every machine.
 */

const DASH = '—';
const NUMBER_LOCALE = 'en-US';
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

export function formatNumber(value: number | null | undefined, opts: { decimals?: number } = {}): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return DASH;
  const d = opts.decimals;
  return value.toLocaleString(NUMBER_LOCALE, d == null ? undefined : { minimumFractionDigits: d, maximumFractionDigits: d });
}

/** A 0 to 1 ratio as a percentage: 0.252 -> "25%". */
export function formatPercent(ratio: number | null | undefined, decimals = 0): string {
  if (typeof ratio !== 'number' || !Number.isFinite(ratio)) return DASH;
  return `${formatNumber(ratio * 100, { decimals })}%`;
}

const DATE_ONLY = /^(\d{4})-(\d{2})-(\d{2})$/;

/**
 * Parse a date. A bare "YYYY-MM-DD" is a calendar day, so it is built in local time. Letting
 * `new Date()` read it as midnight UTC would show the previous day anywhere west of London.
 */
function toDate(input: string | Date | null | undefined): Date | null {
  if (input == null || input === '') return null;
  if (input instanceof Date) return Number.isNaN(input.getTime()) ? null : input;
  const m = DATE_ONLY.exec(input);
  const date = m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : new Date(input);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatDate(input: string | Date | null | undefined): string {
  const d = toDate(input);
  return d ? `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}` : DASH;
}

export function formatDateTime(input: string | Date | null | undefined): string {
  const d = toDate(input);
  if (!d) return DASH;
  const hh = String(d.getHours()).padStart(2, '0');
  const mm = String(d.getMinutes()).padStart(2, '0');
  return `${formatDate(d)}, ${hh}:${mm}`;
}

/** A 24-hour clock time, "09:05". */
export function formatTime(input: string | Date | null | undefined): string {
  const d = toDate(input);
  if (!d) return DASH;
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

/**
 * A group header for one calendar day (v0.5 U11): "Today · Tue 10 Nov", "Yesterday · Mon 9 Nov",
 * "Fri 6 Nov", or with the year when it is not this year. Takes a "YYYY-MM-DD" day (see isoDay).
 */
export function formatDayHeading(day: string | null | undefined, now: Date = new Date()): string {
  const d = day ? toDate(day) : null;
  if (!d) return 'No date';
  const base = `${WEEKDAYS[d.getDay()]} ${d.getDate()} ${MONTHS[d.getMonth()]}`;
  const sameDay = (a: Date, b: Date) => a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
  const yesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1);
  if (sameDay(d, now)) return `Today · ${base}`;
  if (sameDay(d, yesterday)) return `Yesterday · ${base}`;
  return d.getFullYear() === now.getFullYear() ? base : `${base} ${d.getFullYear()}`;
}

/** The calendar day ("2026-09-14") of a date or datetime, or null. Handy for grouping by day. */
export function isoDay(input: string | Date | null | undefined): string | null {
  const d = toDate(input);
  if (!d) return null;
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}
