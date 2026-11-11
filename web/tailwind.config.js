/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // v0.4 redesign tokens (see momboard-ui-redesign/README.md).
        // Names kept stable so existing classes remap; values are the new palette.
        page: '#f7f7f8', // --bg: app background
        surface: '#ffffff', // cards
        sub: '#f3f4f6', // subtle fills, segmented-control track, dividers
        ink: '#111827', // headings, key numbers, primary text
        'ink-2': '#374151', // --text: body text
        muted: '#6b7280', // secondary text, labels, column headers
        hairline: '#e5e7eb', // --line: card and input borders
        accent: '#2f5bea', // primary buttons, links, focus, selected
        'accent-soft': '#e8eefd', // selected nav, filter pills
        'accent-ink': '#1e3a8a', // text on accent-soft
        'focus-ring': '#d6e0fb', // 3px focus ring
        // Status / semantic.
        good: '#12b76a',
        'good-text': '#067647',
        'good-soft': '#ecfdf3',
        warn: '#f79009',
        'warn-text': '#b54708',
        'warn-soft': '#fffaeb',
        crit: '#f04438',
        'crit-text': '#b42318',
        'crit-soft': '#fef3f2',
        // Core tag colours (signal bars + tag pills; pills use a light tint).
        'tag-pain': '#ea580c',
        'tag-obstacle': '#db2777',
        'tag-workaround': '#2563eb',
        'tag-money': '#ca8a04',
        'tag-context': '#9ca3af',
        'tag-followup': '#7c3aed',
        'tag-person': '#0891b2',
        'tag-commitment': '#059669',
        'tag-feature': '#64748b',
        'tag-anger': '#b91c1c',
        'tag-excitement': '#16a34a',
        'tag-compliment': '#d1d5db',
        'tag-neutral': '#9ca3af', // custom tags with no colour
        // Legacy series aliases (kept so existing chart code compiles).
        's1': '#2f5bea',
        's2': '#ea580c',
        's3': '#059669',
        's4': '#ca8a04',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', '"Segoe UI"', 'sans-serif'],
        mono: ['ui-monospace', 'monospace'],
      },
      borderRadius: {
        pill: '50px',
      },
    },
  },
  plugins: [],
};
