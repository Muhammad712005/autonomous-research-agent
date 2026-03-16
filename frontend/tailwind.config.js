/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        deepBlack: "#0a0a0a",
        darkGrey:  "#1a1a1a",
        bloodRed:  "#8b0000",
        crimson:   "#dc143c",
      },
    },
  },
  plugins: [require('@tailwindcss/typography')],
}

