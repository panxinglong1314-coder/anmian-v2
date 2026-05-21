import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

// 开发时把 /api 反代到生产后端,避免浏览器 CORS。
// 上线时由部署平台(Vercel/Cloudflare)或 Nginx 处理同源。
const API_TARGET = process.env.VITE_API_TARGET || "https://sleepai.chat";

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      manifest: {
        name: "ZhiMian — Sleep Companion",
        short_name: "ZhiMian",
        description: "A calm CBT-I companion for the nights your mind won't quiet.",
        theme_color: "#0D1B2A",
        background_color: "#0D1B2A",
        display: "standalone",
        start_url: "/",
        icons: [
          { src: "/icon-192.png", sizes: "192x192", type: "image/png" },
          { src: "/icon-512.png", sizes: "512x512", type: "image/png" }
        ]
      }
    })
  ],
  server: {
    port: 3000,
    proxy: {
      "/api": {
        target: API_TARGET,
        changeOrigin: true,
        secure: true,
        ws: true
      }
    }
  }
});
