/**
 * Tag metadata matching the backend seed taxonomy.
 */
export const TAG_META: Record<string, { emoji: string; name: string }> = {
  pain: { emoji: '⚡', name: 'pain' },
  obstacle: { emoji: '🧱', name: 'obstacle' },
  workaround: { emoji: '➡️', name: 'workaround' },
  emotion_pos: { emoji: '😄', name: 'excitement' },
  emotion_neg: { emoji: '😠', name: 'anger' },
  context: { emoji: '🎯', name: 'context' },
  feature_request: { emoji: '☐', name: 'feature request' },
  money: { emoji: '💰', name: 'money' },
  person: { emoji: '👤', name: 'person' },
  followup: { emoji: '☆', name: 'follow-up' },
  commitment: { emoji: '🤝', name: 'commitment' },
  compliment: { emoji: '🎈', name: 'compliment' },
};

export function tagEmoji(key: string): string {
  return TAG_META[key]?.emoji || '?';
}

export function tagName(key: string): string {
  return TAG_META[key]?.name || key;
}

/**
 * v0.4 score bands (README): <=3 red, 4-5 amber, >=6 green. Returns the CSS
 * class suffix used by the `.score-{low,mid,high}` helpers in index.css, plus
 * the raw fg/bg for inline use (charts, inline styles).
 */
export function scoreBand(score: number): { cls: string; bg: string; fg: string } {
  if (score <= 3) return { cls: 'score-low', bg: '#fef3f2', fg: '#b42318' };
  if (score <= 5) return { cls: 'score-mid', bg: '#fffaeb', fg: '#b54708' };
  return { cls: 'score-high', bg: '#ecfdf3', fg: '#067647' };
}

/**
 * Core tag colours (README). Used for signal bars and tag-pill tints. Custom
 * tags fall back to a neutral grey unless the tag API ever adds a colour field.
 */
export const TAG_COLOR: Record<string, string> = {
  pain: '#ea580c',
  obstacle: '#db2777',
  workaround: '#2563eb',
  money: '#ca8a04',
  context: '#9ca3af',
  followup: '#7c3aed',
  person: '#0891b2',
  commitment: '#059669',
  feature_request: '#64748b',
  emotion_neg: '#b91c1c',
  emotion_pos: '#16a34a',
  compliment: '#d1d5db',
};

const TAG_NEUTRAL = '#9ca3af';

export function tagColor(key: string): string {
  return TAG_COLOR[key] || TAG_NEUTRAL;
}
