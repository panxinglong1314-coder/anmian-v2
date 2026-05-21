/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // 与小程序一致的深色夜间配色
        night: "#0D1B2A",
        "night-card": "#13243A",
        "night-line": "#1B3A5A",
        accent: "#F5C869",
        muted: "#8BA3B9",
        text: "#E0E8F0",
        coral: "#E8846B"
      }
    }
  },
  plugins: []
};
