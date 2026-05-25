import { Navigate, Outlet, Route, Routes } from "react-router-dom";
import { isLoggedIn } from "./lib/auth";
import BottomNav from "./components/BottomNav";
import Landing from "./pages/Landing";
import Login from "./pages/Login";
import Chat from "./pages/Chat";
import Worries from "./pages/Worries";
import Profile from "./pages/Profile";

function AppLayout() {
  if (!isLoggedIn()) return <Navigate to="/login" replace />;
  return (
    <div className="h-full flex flex-col max-w-2xl mx-auto">
      <main className="flex-1 min-h-0">
        <Outlet />
      </main>
      <BottomNav />
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      {/* 营销官网(公开) */}
      <Route path="/" element={<Landing />} />
      <Route path="/login" element={<Login />} />
      {/* 产品(需登录),统一挂在 /app 下 */}
      <Route path="/app" element={<AppLayout />}>
        <Route index element={<Chat />} />
        <Route path="worries" element={<Worries />} />
        <Route path="profile" element={<Profile />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
