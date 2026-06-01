/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // HR 后台:更专业、更克制的深蓝灰 + 金重点色
        bg: "#0A1220",
        card: "#11203A",
        line: "#1B3A5A",
        cardx: "#142845",
        accent: "#F5C869",
        accentdim: "#C09A4E",
        text: "#E0E8F0",
        muted: "#8BA3B9",
        dim: "#5B7390",
        ok: "#7EE0B5",
        warn: "#F0B95B",
        bad: "#E8846B",
      },
    },
  },
  plugins: [],
};
