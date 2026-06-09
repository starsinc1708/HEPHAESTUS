import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{vue,ts}'],
  theme: {
    extend: {
      colors: {
        'arg-bg': 'var(--bg)',
        'arg-panel': 'var(--panel)',
        'arg-panel-2': 'var(--panel-2)',
        'arg-panel-3': 'var(--panel-3)',
        'arg-border': 'var(--border)',
        'arg-border-2': 'var(--border-2)',
        'arg-primary': 'var(--primary)',
        'arg-on-primary': 'var(--on-primary)',
        'arg-text': 'var(--text)',
        'arg-muted': 'var(--muted)',
        'arg-muted-soft': 'var(--muted-soft)',
        'arg-green': 'var(--green)',
        'arg-rose': 'var(--rose)',
        'arg-amber': 'var(--amber)',
        'arg-blue': 'var(--blue)',
        'arg-cyan': 'var(--cyan)',
        'arg-violet': 'var(--violet)',
        'arg-pink': 'var(--pink)',
      },
    },
  },
} satisfies Config
