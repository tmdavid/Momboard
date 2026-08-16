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
