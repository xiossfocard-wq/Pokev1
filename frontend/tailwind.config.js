/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./app/**/*.{js,ts,jsx,tsx,mdx}", "./components/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          950: "#0B0D12",
          900: "#12141B",
          800: "#1A1D26",
          700: "#252934",
          600: "#343A48",
        },
        parchment: {
          100: "#EDEAE1",
        },
        ember: {
          400: "#F0A94E",
          500: "#E8922E",
          600: "#C9761E",
        },
        moss: {
          400: "#5FBE8D",
          500: "#3FA372",
        },
        rust: {
          400: "#E5646A",
          500: "#D8474E",
        },
      },
      fontFamily: {
        display: ["var(--font-display)", "serif"],
        body: ["var(--font-body)", "sans-serif"],
        mono: ["var(--font-mono)", "monospace"],
      },
      borderRadius: {
        sm: "6px",
        md: "10px",
        lg: "16px",
      },
    },
  },
  plugins: [],
};
