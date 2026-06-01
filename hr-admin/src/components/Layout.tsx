import { Link, NavLink, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useEffect, useState } from "react";
import { clearToken, decodeJwtPayload } from "../lib/auth";
import { getMe, type MeResponse } from "../lib/api";
import LangToggle from "./LangToggle";

export default function Layout({ children }: { children: React.ReactNode }) {
  const { t } = useTranslation();
  const nav = useNavigate();
  const [me, setMe] = useState<MeResponse | null>(null);

  useEffect(() => {
    getMe().then(setMe).catch(() => {});
  }, []);

  const signOut = () => {
    clearToken();
    nav("/login", { replace: true });
  };

  const linkCls = ({ isActive }: { isActive: boolean }) =>
    `block px-4 py-2.5 rounded-md text-sm transition ${
      isActive
        ? "bg-accent/15 text-accent border-l-2 border-accent"
        : "text-muted hover:text-text hover:bg-card/50"
    }`;

  return (
    <div className="h-full flex bg-bg">
      {/* Sidebar */}
      <aside className="w-60 shrink-0 border-r border-line bg-card/30 flex flex-col">
        <div className="px-5 py-5 border-b border-line">
          <Link to="/" className="font-bold text-text">
            知眠<span className="text-accent">.</span>
          </Link>
          <div className="text-[11px] text-muted mt-0.5">{t("layout.subtitle")}</div>
        </div>

        <nav className="flex-1 py-3 px-3 space-y-0.5">
          <NavLink to="/" end className={linkCls}>📊 {t("nav.overview")}</NavLink>
          <NavLink to="/teams" className={linkCls}>🧑‍🤝‍🧑 {t("nav.teams")}</NavLink>
          <NavLink to="/employees" className={linkCls}>📥 {t("nav.employees")}</NavLink>
          <NavLink to="/reports" className={linkCls}>📑 {t("nav.reports")}</NavLink>
          <NavLink to="/settings" className={linkCls}>⚙️ {t("nav.settings")}</NavLink>
        </nav>

        <div className="border-t border-line p-4 text-xs text-muted space-y-2">
          {me?.org && (
            <div>
              <div className="text-text font-medium text-sm truncate">🏢 {me.org.org_name}</div>
              <div className="text-dim mt-0.5">{me.openid}</div>
            </div>
          )}
          <div className="flex items-center justify-between gap-2 pt-2 border-t border-line">
            <LangToggle />
            <button onClick={signOut} className="text-bad hover:underline">
              {t("nav.signOut")}
            </button>
          </div>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 overflow-y-auto">
        <div className="max-w-6xl mx-auto p-6 md:p-8">{children}</div>
      </main>
    </div>
  );
}
