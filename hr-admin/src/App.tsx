import { lazy, Suspense } from "react";
import { Navigate, Outlet, Route, Routes } from "react-router-dom";
import { isLoggedIn, isHrAdmin } from "./lib/auth";
import Layout from "./components/Layout";

const Login = lazy(() => import("./pages/Login"));
const Overview = lazy(() => import("./pages/Overview"));
const Teams = lazy(() => import("./pages/Teams"));
const Employees = lazy(() => import("./pages/Employees"));
const Reports = lazy(() => import("./pages/Reports"));
const Settings = lazy(() => import("./pages/Settings"));
const NotFound = lazy(() => import("./pages/NotFound"));

function Loading() {
  return (
    <div className="h-full flex items-center justify-center text-muted text-sm">
      <span className="text-3xl animate-pulse">📊</span>
    </div>
  );
}

function Guard() {
  if (!isLoggedIn()) return <Navigate to="/login" replace />;
  if (!isHrAdmin()) return <Navigate to="/login?reason=no_hr_role" replace />;
  return (
    <Layout>
      <Outlet />
    </Layout>
  );
}

export default function App() {
  return (
    <Suspense fallback={<Loading />}>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route element={<Guard />}>
          <Route path="/" element={<Overview />} />
          <Route path="/teams" element={<Teams />} />
          <Route path="/employees" element={<Employees />} />
          <Route path="/reports" element={<Reports />} />
          <Route path="/settings" element={<Settings />} />
        </Route>
        <Route path="*" element={<NotFound />} />
      </Routes>
    </Suspense>
  );
}
