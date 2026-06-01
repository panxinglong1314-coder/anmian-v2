import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 开发时把 /api 反代到生产后端,避免浏览器 CORS。
// 上线时由 Nginx /hr-admin/ 映射到本应用的 dist/,API 同源。
const API_TARGET = process.env.VITE_API_TARGET || "https://sleepai.chat";

export default defineConfig({
  base: "/hr-admin/",   // 部署在 https://sleepai.chat/hr-admin/
  plugins: [react()],
  server: {
    port: process.env.PORT ? Number(process.env.PORT) : 3001,
    proxy: {
      "/api": {
        target: API_TARGET,
        changeOrigin: true,
        secure: true,
      },
    },
  },
});
