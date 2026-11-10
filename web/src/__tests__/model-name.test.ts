import { describe, test, expect } from 'vitest';
import { friendlyModelName } from '../utils/modelName';

describe('friendlyModelName', () => {
  test('maps known Bedrock inference-profile ids to clean names', () => {
    expect(friendlyModelName('eu.anthropic.claude-haiku-5-5')).toBe('Claude Haiku 5.5');
    expect(friendlyModelName('eu.anthropic.claude-sonnet-5-5')).toBe('Claude Sonnet 5.5');
  });

  test('maps OpenAI + local ids', () => {
    expect(friendlyModelName('gpt-5-mini')).toBe('GPT-5 mini');
    expect(friendlyModelName('qwen3:8b')).toBe('Qwen3 8B (local)');
  });

  test('NEVER exposes an account id from a full Bedrock ARN', () => {
    const arn =
      'arn:aws:bedrock:eu-west-1:499557161408:application-inference-profile/md4yu43kmqzf';
    const out = friendlyModelName(arn);
    expect(out).not.toContain('499557161408');
    expect(out).not.toContain('arn:aws');
    expect(out).not.toContain('md4yu43kmqzf');
  });

  test('a known-model ARN still maps to the friendly name', () => {
    const arn = 'arn:aws:bedrock:eu-west-1:499557161408:inference-profile/eu.anthropic.claude-haiku-5-5';
    expect(friendlyModelName(arn)).toBe('Claude Haiku 5.5');
  });

  test('unknown token with a long digit run is scrubbed, not shown', () => {
    expect(friendlyModelName('someprofile-499557161408')).toBe('Custom model');
  });

  test('empty/null is empty string', () => {
    expect(friendlyModelName(null)).toBe('');
    expect(friendlyModelName('')).toBe('');
  });
});
