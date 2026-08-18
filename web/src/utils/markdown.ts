export type MarkdownVariant = 'notes' | 'digest';

/**
 * Render the deliberately small MomBoard markdown subset safely.
 *
 * User and generated content is escaped before any markup is introduced, so
 * raw HTML, event attributes, encoded protocols, SVG, and malformed tags stay
 * visible as text. Only the tags generated below can reach the DOM.
 */
export function renderSafeMarkdown(markdown: string, variant: MarkdownVariant): string {
  let html = escapeHtml(markdown);

  if (variant === 'digest') {
    html = html
      .replace(/^# (.*)$/gm, '<h2 class="text-lg font-bold mt-4 mb-1">$1</h2>')
      .replace(/^## (.*)$/gm, '<h3 class="text-base font-semibold mt-3 mb-1">$1</h3>')
      .replace(/^- \*\*(.*?)\*\*(.*)$/gm, '<li><b>$1</b>$2</li>');
  } else {
    html = html
      .replace(/^# (.*)$/gm, '<h3>$1</h3>')
      .replace(/^## (.*)$/gm, '<h4>$1</h4>');
  }

  return html
    .replace(/^- (.*)$/gm, '<li>$1</li>')
    .replace(/\*\*(.*?)\*\*/g, '<b>$1</b>')
    .replace(/\*(.*?)\*/g, '<i>$1</i>')
    .replace(/\n\n/g, '<br>');
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
