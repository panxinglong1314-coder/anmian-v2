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
      // 本域名根路径 "/" 是独立的静态营销站,SPA 仅在 /login、/app 下。
      // 作用域为 "/" 的 Service Worker 会在刷新时用 SPA 外壳劫持营销首页,
      // 且无法自更新(/sw.js 被静态站点遮蔽返回 404)。因此关闭 PWA 缓存,
      // 改为生成「自毁」SW —— 它会注销自身并清空缓存,清除历史遗留的 SW。
      selfDestroying: true,
      registerType: "autoUpdate",
      workbox: {
        // SPA 与 /admin、/api 等共用同一域名:SW 的导航兜底不能吞掉这些路径,
        // 否则浏览器里打开 /admin/ 会被 SW 换成 SPA 的 index.html(后台打不开)。
        navigateFallbackDenylist: [/^\/admin/, /^\/api\//, /^\/static\//]
      },
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
    port: process.env.PORT ? Number(process.env.PORT) : 3000,
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
