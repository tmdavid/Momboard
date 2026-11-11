import { describe, expect, test } from 'vitest';
import { formatDate, formatDateTime, formatNumber, formatPercent, isoDay } from '../utils/format';

describe('formatNumber', () => {
  test.each([
    [0, '0'], [7, '7'], [999, '999'], [1000, '1,000'], [14249, '14,249'], [1234567, '1,234,567'], [-2500, '-2,500'],
  ])('%d -> %s', (n, expected) => expect(formatNumber(n)).toBe(expected));

  test('keeps decimals when asked and rounds to the requested places', () => {
    expect(formatNumber(1234.5678, { decimals: 1 })).toBe('1,234.6');
    expect(formatNumber(3, { decimals: 2 })).toBe('3.00');
  });

  test('missing or non-numeric values render as a dash, never NaN', () => {
    expect(formatNumber(null)).toBe('—');
    expect(formatNumber(undefined)).toBe('—');
    expect(formatNumber(Number.NaN)).toBe('—');
    expect(formatNumber(Number.POSITIVE_INFINITY)).toBe('—');
  });
});

describe('formatPercent', () => {
  test('takes a 0-1 ratio', () => {
    expect(formatPercent(0.252)).toBe('25%');
    expect(formatPercent(1)).toBe('100%');
    expect(formatPercent(0.1234, 1)).toBe('12.3%');
    expect(formatPercent(null)).toBe('—');
  });
});

describe('formatDate', () => {
  test('is "14 Sep 2026", never an ISO string', () => {
    expect(formatDate('2026-09-14T12:30:00Z')).toBe('14 Sep 2026');
    expect(formatDate('2026-09-14T12:30:00')).toBe('14 Sep 2026');
    expect(formatDate(new Date(2026, 8, 14, 9, 0))).toBe('14 Sep 2026');
  });

  test('a date-only string is the same calendar day in every timezone', () => {
    // new Date("2026-09-14") is midnight UTC, which is 13 Sep in the Americas. We must not shift it.
    expect(formatDate('2026-09-14')).toBe('14 Sep 2026');
    expect(formatDate('2026-01-01')).toBe('1 Jan 2026');
  });

  test('single-digit days are not padded', () => {
    expect(formatDate('2026-03-02')).toBe('2 Mar 2026');
  });

  test('missing or invalid dates render as a dash', () => {
    expect(formatDate(null)).toBe('—');
    expect(formatDate(undefined)).toBe('—');
    expect(formatDate('')).toBe('—');
    expect(formatDate('not a date')).toBe('—');
  });
});

describe('formatDateTime', () => {
  test('adds the time of day in 24-hour form', () => {
    expect(formatDateTime(new Date(2026, 8, 14, 9, 5))).toBe('14 Sep 2026, 09:05');
    expect(formatDateTime(new Date(2026, 8, 14, 21, 30))).toBe('14 Sep 2026, 21:30');
    expect(formatDateTime(null)).toBe('—');
  });
});

describe('isoDay', () => {
  test('takes the calendar day from a date or datetime', () => {
    expect(isoDay('2026-09-14T23:59:00')).toBe('2026-09-14');
    expect(isoDay('2026-09-14')).toBe('2026-09-14');
    expect(isoDay('nonsense')).toBeNull();
  });
});
