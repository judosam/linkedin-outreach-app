/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ['class', '[data-theme="dark"]'],
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        canvas: 'var(--bg)',
        surface: 'var(--surface)',
        surfaceSolid: 'var(--surface-solid)',
        inset: 'var(--inset)',
        line: 'var(--border)',
        lineStrong: 'var(--border-strong)',
        ink: 'var(--text)',
        ink2: 'var(--text-2)',
        muted: 'var(--muted)',
        nav: 'var(--nav)',
        navSoft: 'var(--nav-2)',
        primary: {
          DEFAULT: 'var(--primary)',
          hover: 'var(--primary-hover)',
          tint: 'var(--primary-tint)',
          ink: 'var(--primary-ink)',
        },
        ok: 'var(--ok)',
        warn: 'var(--warn)',
        crit: 'var(--crit)',
        info: 'var(--info)',
      },
      borderRadius: {
        control: '10px',
        panel: '16px',
      },
      boxShadow: {
        border: 'var(--shadow-border)',
        lift: 'var(--shadow-lift)',
        pop: 'var(--shadow-pop)',
      },
      fontFamily: {
        sans: ['Geist', 'system-ui', '-apple-system', 'Segoe UI', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      maxWidth: { content: '1600px' },
      transitionTimingFunction: {
        out: 'cubic-bezier(0.2, 0, 0, 1)',
      },
    },
  },
  plugins: [],
};
