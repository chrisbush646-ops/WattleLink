/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./templates/**/*.html",
    "./apps/**/*.py",
    "./apps/**/*.html",
  ],
  theme: {
    extend: {
      colors: {
        ink: {
          DEFAULT: "#121613",
          soft: "#2A302C",
        },
        muted: {
          DEFAULT: "#6A706A",
          soft: "#9AA09A",
        },
        line: {
          DEFAULT: "#E3DFD0",
          soft: "#EFEBDE",
        },
        paper: {
          DEFAULT: "#F6F2E7",
          warm: "#FAF7EE",
        },
        surface: "#FFFFFF",
        euc: {
          DEFAULT: "#264032",
          dark: "#1A2E23",
          light: "#3C5C4A",
        },
        wattle: {
          DEFAULT: "#C89B2A",
          light: "#E5BE5A",
          soft: "#F6E9BF",
        },
        coral: {
          DEFAULT: "#B85C3A",
          soft: "#F6E1D6",
        },
        sky: {
          DEFAULT: "#4B6E84",
          soft: "#DCE6EC",
        },
      },
      fontFamily: {
        serif: ["Fraunces", "Iowan Old Style", "Georgia", "serif"],
        sans: ["Geist", "ui-sans-serif", "system-ui", "-apple-system", "sans-serif"],
        mono: ["Geist Mono", "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      borderRadius: {
        DEFAULT: "8px",
        lg: "14px",
      },
    },
  },
  plugins: [],
};
