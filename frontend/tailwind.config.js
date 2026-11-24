/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        'canvas-green':   '#00ff88',
        'canvas-amber':   '#ffbb00',
        'canvas-red':     '#ff4444',
        'canvas-blue':    '#79c0ff',
        'canvas-dark':    '#0d1117',
        'canvas-surface': '#161b22',
        'canvas-surface2':'#1c2128',
        'canvas-border':  '#30363d',
        'canvas-muted':   '#8b949e',
        'canvas-text':    '#e6edf3',
      },
      fontFamily: {
        mono: ['JetBrains Mono', 'Fira Code', 'Cascadia Code', 'Consolas', 'monospace'],
      },
    },
  },
  plugins: [],
}
