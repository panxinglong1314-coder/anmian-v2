import { Navigate, Outlet, Route, Routes } from "react-router-dom";
import { isLoggedIn } from "./lib/auth";
import BottomNav from "./components/BottomNav";
import Landing from "./pages/Landing";
import Login from "./pages/Login";
import Chat from "./pages/Chat";
import Sleep from "./pages/Sleep";
import Worries from "./pages/Worries";
import Profile from "./pages/Profile";
import Privacy from "./pages/Privacy";
import Terms from "./pages/Terms";
import Contact from "./pages/Contact";

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
    <Routes>
      {/* 营销官网(公开) */}
      <Route path="/" element={<Landing />} />
      <Route path="/login" element={<Login />} />
      {/* 法律/联系页(公开,双语) */}
      <Route path="/privacy" element={<Privacy />} />
      <Route path="/terms" element={<Terms />} />
      <Route path="/contact" element={<Contact />} />
      {/* 产品(需登录),统一挂在 /app 下 */}
      <Route path="/app" element={<AppLayout />}>
        <Route index element={<Chat />} />
        <Route path="sleep" element={<Sleep />} />
        <Route path="worries" element={<Worries />} />
        <Route path="profile" element={<Profile />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
