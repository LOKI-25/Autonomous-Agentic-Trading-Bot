/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./src/**/*.{html,ts}", // This ensures Tailwind scans your components
  ],
  theme: {
    extend: {},
  },
  plugins: [require('@tailwindcss/typography')],
}
