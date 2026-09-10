/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"Inter Variable"', 'Inter', '-apple-system', 'BlinkMacSystemFont', '"Segoe UI"', 'Roboto', 'sans-serif'],
        mono: ['"JetBrains Mono Variable"', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      colors: {
        accent: 'var(--accent)',
        ink: 'var(--ink)',
        bg: 'var(--bg)',
        green: 'var(--pos)', red: 'var(--neg)', orange: 'var(--warn)',
        yellow: '#eab308', purple: '#7c3aed', teal: '#0891b2', pink: '#db2777', indigo: '#4f46e5',
      },
      borderRadius: {
        lg: 'calc(10px * var(--r-k, 1))', xl: 'calc(12px * var(--r-k, 1))', '2xl': 'calc(20px * var(--r-k, 1))', '3xl': 'calc(28px * var(--r-k, 1))',
        '4xl': 'calc(26px * var(--r-k, 1))',
      },
      keyframes: {
        rise: { from: { opacity: 0, transform: 'translateY(8px)' }, to: { opacity: 1, transform: 'translateY(0)' } },
        pulseSoft: { '0%,100%': { opacity: 1 }, '50%': { opacity: .45 } },
      },
      animation: { rise: 'rise .35s cubic-bezier(.2,.8,.2,1) both', pulseSoft: 'pulseSoft 1.6s ease-in-out infinite' },
    },
  },
  plugins: [],
}
