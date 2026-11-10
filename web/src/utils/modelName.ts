/**
 * Turn a raw LLM model identifier into a friendly display name.
 *
 * The backend stores whatever the client reported as the model — which for the
 * Bedrock backend can be a full inference-profile ARN that embeds the AWS account
 * ID (e.g. "arn:aws:bedrock:eu-west-1:499557161408:application-inference-profile/...").
 * That must never be shown in the UI. This maps known ids to clean labels and, for
 * anything unrecognized, strips it down to a safe, account-id-free token.
 */

const FRIENDLY: Record<string, string> = {
  // Anthropic (Bedrock inference-profile ids, with/without region prefix)
  'claude-haiku-5-5': 'Claude Haiku 5.5',
  'claude-sonnet-5-5': 'Claude Sonnet 5.5',
  'claude-opus-5-5': 'Claude Opus 5.5',
  // OpenAI
  'gpt-5-mini': 'GPT-5 mini',
  'gpt-4o': 'GPT-4o',
  'gpt-4o-mini': 'GPT-4o mini',
  // Local
  'qwen3:8b': 'Qwen3 8B (local)',
};

export function friendlyModelName(model: string | null | undefined): string {
  if (!model) return '';

  // Known ids anywhere in the string (handles "eu.anthropic.claude-haiku-5-5",
  // base ids, and ARNs whose tail contains the model id).
  for (const [id, label] of Object.entries(FRIENDLY)) {
    if (model.includes(id)) return label;
  }

  // Unknown ARN → never expose account id / profile id. Reduce to a generic label.
  if (model.startsWith('arn:aws:bedrock')) return 'Amazon Bedrock model';

  // Unknown but not an ARN: show at most the last path segment, and refuse anything
  // that still looks like it contains a long digit run (account-id-like).
  const tail = model.split('/').pop() ?? model;
  if (/\d{6,}/.test(tail)) return 'Custom model';
  return tail;
}
