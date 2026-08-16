/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        page: '#f9f9f7',
        surface: '#fcfcfb',
        ink: '#0b0b0b',
        'ink-2': '#52514e',
        muted: '#898781',
        hairline: '#e1e0d9',
        accent: '#2a78d6',
        'accent-soft': '#e8f1fc',
        good: '#0ca30c',
        'good-text': '#006300',
        warn: '#fab219',
        crit: '#d03b3b',
        's1': '#2a78d6',
        's2': '#eb6834',
        's3': '#1baf7a',
        's4': '#eda100',
      },
      fontFamily: {
        sans: ['system-ui', '-apple-system', '"Segoe UI"', 'sans-serif'],
        mono: ['ui-monospace', 'monospace'],
      },
    },
  },
  plugins: [],
};
