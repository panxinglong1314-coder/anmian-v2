/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // App(产品)配色
        night: "#0D1B2A",
        "night-card": "#13243A",
        "night-line": "#1B3A5A",
        accent: "#F5C869",
        muted: "#8BA3B9",
        text: "#E0E8F0",
        coral: "#E8846B",
        // Landing(营销官网)配色 — 沿用原静态官网的深空 + 金
        deep: "#06060f",
        navyx: "#0d0d1e",
        cardx: "#111128",
        gold: "#c9956a",
        goldlight: "#e8c9a0",
        txt2: "#8888a0",
        txt3: "#55556a"
      }
    }
  },
  plugins: []
};
