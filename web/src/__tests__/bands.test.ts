import { describe, test, expect } from 'vitest';
import { computeBand, DEFAULT_BAND_RULES } from '../utils/bands';

// Must stay in step with PRD_CASES in tests/test_hypothesis_grounding.py (the server's rules).
const CASES: [number, number, number, string][] = [
  [0, 0, 0, 'hunch'],
  [1, 0, 1, 'candidate'],
  [2, 0, 2, 'candidate'],
  [3, 0, 1, 'candidate'],
  [5, 0, 1, 'candidate'],
  [3, 0, 2, 'grounded'],
  [3, 1, 2, 'grounded'],
  [6, 1, 4, 'grounded'],
  [2, 2, 2, 'contested'],
  [3, 2, 2, 'contested'],
  [4, 3, 3, 'contested'],
  [0, 3, 0, 'refuted'],
  [1, 3, 1, 'refuted'],
  [1, 4, 1, 'refuted'],
  [2, 5, 2, 'refuted'],
  [1, 1, 1, 'candidate'],
  [0, 1, 0, 'candidate'],
  [0, 2, 0, 'candidate'],
  [2, 3, 2, 'contested'],
  [1, 2, 1, 'candidate'],
];

describe('computeBand (mirrors the server rules)', () => {
  test.each(CASES)('%i supporting, %i contradicting, %i companies -> %s', (sup, con, co, expected) => {
    expect(computeBand(sup, con, co)).toBe(expected);
  });

  test('uses the thresholds it is given', () => {
    const strict = { ...DEFAULT_BAND_RULES, grounded_min_support: 5, grounded_min_companies: 3 };
    expect(computeBand(3, 0, 2, strict)).toBe('candidate');
    expect(computeBand(5, 0, 3, strict)).toBe('grounded');
  });
});
