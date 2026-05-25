import { NavLink } from "react-router-dom";
import { useTranslation } from "react-i18next";

const tabs = [
  { to: "/app", icon: "🌙", key: "nav.chat", end: true },
  { to: "/app/worries", icon: "📥", key: "nav.worries", end: false },
  { to: "/app/profile", icon: "👤", key: "nav.profile", end: false }
];

export default function BottomNav() {
  const { t } = useTranslation();
  return (
    <nav className="h-14 flex-shrink-0 border-t border-night-line flex items-stretch">
      {tabs.map((tab) => (
        <NavLink
          key={tab.to}
          to={tab.to}
          end={tab.end}
          className={({ isActive }) =>
            `flex-1 flex flex-col items-center justify-center gap-0.5 text-[11px] transition ${
              isActive ? "text-accent" : "text-muted hover:text-text"
            }`
          }
        >
          <span className="text-lg leading-none">{tab.icon}</span>
          <span>{t(tab.key)}</span>
        </NavLink>
      ))}
    </nav>
  );
}
