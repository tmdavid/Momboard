/**
 * Grounding-band rules, mirrored from the server (app/services/hypothesis_grounding.py).
 * The server is the source of truth for saved hypotheses; this exists only so the
 * composer can preview "If saved now: X" while the user ticks quotes. The live
 * thresholds are fetched from GET /api/hypotheses/band-rules; DEFAULT_BAND_RULES are
 * the PRD numbers, used until that response arrives.
 */
export interface BandRules {
  grounded_min_support: number;
  grounded_min_companies: number;
  grounded_max_contradict: number;
  contested_min_each: number;
  refuted_min_contradict: number;
  refuted_ratio: number;
}

export const DEFAULT_BAND_RULES: BandRules = {
  grounded_min_support: 3,
  grounded_min_companies: 2,
  grounded_max_contradict: 1,
  contested_min_each: 2,
  refuted_min_contradict: 3,
  refuted_ratio: 2,
};

export type BandKey = 'grounded' | 'contested' | 'candidate' | 'hunch' | 'refuted';

/** Band for CONFIRMED counts only — suggested/unticked quotes never count. */
export function computeBand(
  supporting: number,
  contradicting: number,
  companiesSupporting: number,
  rules: BandRules = DEFAULT_BAND_RULES,
): BandKey {
  if (supporting === 0 && contradicting === 0) return 'hunch';
  if (contradicting >= rules.refuted_min_contradict && contradicting > rules.refuted_ratio * supporting) {
    return 'refuted';
  }
  if (supporting >= rules.contested_min_each && contradicting >= rules.contested_min_each) {
    return 'contested';
  }
  if (
    supporting >= rules.grounded_min_support &&
    companiesSupporting >= rules.grounded_min_companies &&
    contradicting <= rules.grounded_max_contradict
  ) {
    return 'grounded';
  }
  return 'candidate';
}

export const BAND_LABEL: Record<BandKey, string> = {
  grounded: 'Grounded',
  contested: 'Contested',
  candidate: 'Candidate',
  hunch: 'Hunch',
  refuted: 'Refuted',
};
