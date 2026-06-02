import { lazy, Suspense } from "react";
import { Navigate, Outlet, Route, Routes } from "react-router-dom";
const NotFound = lazy(() => import("./pages/NotFound"));
import { isLoggedIn } from "./lib/auth";
import BottomNav from "./components/BottomNav";
import Landing from "./pages/Landing"; // eager: landing is the LCP entry route

// Code-split everything else so the landing page ships minimal JS.
const Login = lazy(() => import("./pages/Login"));
const Chat = lazy(() => import("./pages/Chat"));
const Sleep = lazy(() => import("./pages/Sleep"));
const Worries = lazy(() => import("./pages/Worries"));
const Profile = lazy(() => import("./pages/Profile"));
const Subscribe = lazy(() => import("./pages/Subscribe"));
const Privacy = lazy(() => import("./pages/Privacy"));
const Terms = lazy(() => import("./pages/Terms"));
const Contact = lazy(() => import("./pages/Contact"));
const Enterprise = lazy(() => import("./pages/Enterprise"));
import MarketingShell from "./components/MarketingShell";

function Loading() {
  return (
    <div className="h-full flex items-center justify-center text-muted text-sm">
      <span className="text-2xl animate-pulse">🌙</span>
    </div>
  );
}

function AppLayout() {
  if (!isLoggedIn()) return <Navigate to="/login" replace />;
  return (
    <div className="starfield starfield-dim h-full flex flex-col max-w-2xl mx-auto">
      <main className="flex-1 min-h-0">
        <Outlet />
      </main>
      <BottomNav />
    </div>
  );
}

export default function App() {
  return (
    <Suspense fallback={<Loading />}>
      <Routes>
        {/* 营销/登录页 — 用 MarketingShell 共享持久化视频背景,
            路由切换时视频不重新挂载,避免"图片闪一下再视频"的感受 */}
        <Route element={<MarketingShell />}>
          <Route path="/" element={<Landing />} />
          <Route path="/login" element={<Login />} />
          <Route path="/enterprise" element={<Enterprise />} />
        </Route>
        {/* 法律/联系页(公开,双语) — 不需要 hero 视频 */}
        <Route path="/privacy" element={<Privacy />} />
        <Route path="/terms" element={<Terms />} />
        <Route path="/contact" element={<Contact />} />
        {/* 产品(需登录),统一挂在 /app 下 */}
        <Route path="/app" element={<AppLayout />}>
          <Route index element={<Chat />} />
          <Route path="sleep" element={<Sleep />} />
          <Route path="subscribe" element={<Subscribe />} />
          <Route path="worries" element={<Worries />} />
          <Route path="profile" element={<Profile />} />
        </Route>
        <Route path="*" element={<NotFound />} />
      </Routes>
    </Suspense>
  );
}
