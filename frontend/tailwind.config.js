/** @type {import('tailwindcss').Config} */
// Tokens from the Stitch DESIGN.md: dark slate chrome, crisp light workspace,
// indigo primary, Geist UI + JetBrains Mono data, semantic status palette.
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        chrome: {
          900: '#0F172A',
          800: '#1E293B',
          700: '#334155',
          400: '#94A3B8',
        },
        canvas: '#F8FAFC',
        hairline: '#E2E8F0',
        accentline: '#CBD5E1',
        inset: '#F1F5F9',
        primary: {
          DEFAULT: '#4F46E5',
          hover: '#4338CA',
          active: '#3730A3',
          subdued: '#EEF2FF',
        },
        violet: '#7C3AED',
        ok: { text: '#065F46', bg: '#ECFDF5', border: '#A7F3D0', dot: '#10B981' },
        warn: { text: '#92400E', bg: '#FFFBEB', border: '#FDE68A', dot: '#F59E0B' },
        crit: { text: '#991B1B', bg: '#FEF2F2', border: '#FECACA', dot: '#EF4444' },
        idle: { text: '#475569', bg: '#F1F5F9', border: '#CBD5E1', dot: '#94A3B8' },
      },
      fontFamily: {
        ui: ['Geist', 'Inter', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
      },
      fontSize: {
        // high-density scale from DESIGN.md
        'metric': ['22px', { lineHeight: '28px', letterSpacing: '-0.03em', fontWeight: '600' }],
        'metric-sm': ['13px', { lineHeight: '16px', fontWeight: '500' }],
        'label-code': ['11px', { lineHeight: '14px', letterSpacing: '0.02em', fontWeight: '500' }],
        'th': ['11px', { lineHeight: '14px', letterSpacing: '0.04em', fontWeight: '600' }],
      },
      boxShadow: {
        card: '0 1px 2px 0 rgba(15,23,42,0.04), 0 1px 3px -1px rgba(15,23,42,0.06)',
        raise: '0 4px 6px -1px rgba(15,23,42,0.07), 0 2px 4px -2px rgba(15,23,42,0.05)',
        overlay: '0 10px 15px -3px rgba(15,23,42,0.08), 0 4px 6px -4px rgba(15,23,42,0.03)',
      },
      borderRadius: {
        card: '12px',
        control: '6px',
      },
    },
  },
  plugins: [],
}
