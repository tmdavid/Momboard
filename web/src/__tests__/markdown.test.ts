import { describe, expect, it } from 'vitest';
import { renderSafeMarkdown } from '../utils/markdown';

describe('renderSafeMarkdown', () => {
  it.each(['notes', 'digest'] as const)('escapes raw HTML before rendering %s markdown', (variant) => {
    const output = renderSafeMarkdown(
      '# Safe\n\n<img src=x onerror="alert(1)"><svg onload=alert(2)></svg><a href="&#106;avascript:alert(3)">x</a>',
      variant,
    );

    expect(output).not.toContain('<img');
    expect(output).not.toContain('<svg');
    expect(output).not.toContain('<a ');
    expect(output).toContain('&lt;img');
    expect(output).toContain(variant === 'digest' ? '<h2' : '<h3>Safe</h3>');
  });

  it('renders only the supported emphasis and list markup', () => {
    expect(renderSafeMarkdown('- **Action** now', 'digest')).toBe('<li><b>Action</b> now</li>');
  });
});
