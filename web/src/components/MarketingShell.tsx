import { Outlet } from "react-router-dom";

/**
 * 营销/登录页统一外壳:把 hero 视频做成跨路由持久化背景。
 *
 * 为什么:之前每个页面(/、/enterprise、/login)各自 mount 一个 <video>,
 * 路由切换时 React 会 unmount + remount,浏览器先画 poster 再下载视频 →
 * 用户看到"图片 → 跳一下 → 视频"的闪。
 *
 * 现在视频挂在这一层,路由切换时 <Outlet/> 重渲染但 <video> 不动,
 * 视频保持连续播放,觉得页面像一个有持久背景的"应用"。
 */
export default function MarketingShell() {
  return (
    <div className="relative min-h-full">
      {/* 全局背景视频 — fixed 铺满 viewport, z-0
          无 poster: 视频加载前显示纯深色(MarketingShell 的 bg-deep 兜底),
          避免出现"图片先闪一下再视频"的体验 */}
      <video
        autoPlay
        muted
        loop
        playsInline
        preload="auto"
        className="fixed inset-0 w-full h-full object-cover z-0 pointer-events-none bg-deep"
      >
        <source src="/hero.mp4" type="video/mp4" />
      </video>
      {/* 暗色叠层 — 保持文字可读, z-10 */}
      <div className="fixed inset-0 bg-gradient-to-b from-deep/75 to-deep/92 z-10 pointer-events-none" />
      {/* 页面内容 — z-20 */}
      <div className="relative z-20">
        <Outlet />
      </div>
    </div>
  );
}
