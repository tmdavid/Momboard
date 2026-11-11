/** Read a positive whole number from a query string value, or null for anything else ("abc", "", "-3", "1.5"). */
export function positiveInt(value: string | null | undefined): number | null {
  if (value == null || !/^\d+$/.test(value)) return null;
  const n = Number(value);
  return Number.isSafeInteger(n) && n > 0 ? n : null;
}
