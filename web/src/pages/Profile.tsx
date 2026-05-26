import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { clearToken, getUserEmail, getUserId } from "../lib/auth";
import { deleteAccount, getUsage, AuthError, type Usage } from "../lib/api";
import LanguageToggle from "../components/LanguageToggle";

export default function Profile() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [usage, setUsage] = useState<Usage | null>(null);

  const email = getUserEmail();
  const userId = getUserId();

  useEffect(() => {
    getUsage().then((u) => setUsage(u)).catch(() => {});
  }, []);

  const signOut = () => {
    clearToken();
    navigate("/login", { replace: true });
  };

  const doDelete = async () => {
    setBusy(true);
    setError(null);
    try {
      await deleteAccount();
      clearToken();
      navigate("/login", { replace: true });
    } catch (e) {
      if (e instanceof AuthError) {
        clearToken();
        navigate("/login", { replace: true });
      } else {
        setError(t("profile.deleteError"));
        setBusy(false);
      }
    }
  };

  return (
    <div className="h-full flex flex-col">
      <header className="px-4 py-3 border-b border-night-line flex items-center justify-between">
        <h1 className="font-semibold text-accent">👤 {t("nav.profile")}</h1>
        <LanguageToggle />
      </header>

      <div className="flex-1 overflow-y-auto no-scrollbar px-4 py-5 space-y-5">
        {/* Account card */}
        <div className="rounded-xl bg-night-card border border-night-line px-4 py-4">
          <div className="text-3xl mb-2">🌙</div>
          <div className="text-text text-[15px]">{email || t("profile.anonymous")}</div>
          <div className="text-muted text-[11px] font-mono mt-1">ID: {userId}</div>
        </div>

        {/* Subscription / usage */}
        <Link
          to="/app/subscribe"
          className="block rounded-xl bg-night-card border border-night-line px-4 py-4 hover:border-accent/50 transition"
        >
          <div className="flex items-center justify-between">
            <span className="text-text text-sm">✨ {t("subscribe.title")}</span>
            <span className="text-accent text-sm">
              {usage ? t(`subscribe.tier.${usage.tier}`) : "›"}
            </span>
          </div>
          {usage && (
            <div className="text-[11px] text-muted mt-1">
              {t("subscribe.text")} {usage.text.remaining_minutes ?? Math.floor(usage.text.remaining / 300)}/
              {usage.text.limit_minutes ?? Math.floor(usage.text.limit / 300)} {t("subscribe.minutes")} ·{" "}
              {usage.period === "month" ? t("subscribe.perMonth") : t("subscribe.perDay")}
            </div>
          )}
        </Link>

        {/* About */}
        <div className="rounded-xl bg-night-card border border-night-line divide-y divide-night-line">
          <div className="px-4 py-3 text-sm text-muted">{t("profile.aboutLine")}</div>
          <div className="px-4 py-3 text-[11px] text-muted/70 leading-relaxed">
            {t("profile.disclaimer")}
          </div>
        </div>

        {/* Sign out */}
        <button
          onClick={signOut}
          className="w-full rounded-lg border border-night-line text-text py-2.5 hover:bg-night-card transition"
        >
          {t("common.signOut")}
        </button>

        {/* Delete account */}
        <button
          onClick={() => setConfirming(true)}
          className="w-full text-coral/80 text-xs py-2 hover:text-coral transition"
        >
          {t("profile.deleteAccount")}
        </button>

        {error && <p className="text-coral text-sm text-center">{error}</p>}
      </div>

      {/* Delete confirm overlay */}
      {confirming && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center px-6 z-50">
          <div className="bg-night-card border border-night-line rounded-2xl p-5 w-full max-w-sm">
            <div className="text-2xl text-center mb-2">⚠️</div>
            <h3 className="text-text font-semibold text-center">{t("profile.deleteTitle")}</h3>
            <p className="text-muted text-sm mt-2 leading-relaxed">{t("profile.deleteWarn")}</p>
            <div className="flex gap-2 mt-5">
              <button
                onClick={() => setConfirming(false)}
                disabled={busy}
                className="flex-1 rounded-lg border border-night-line text-text py-2.5 transition"
              >
                {t("profile.deleteCancel")}
              </button>
              <button
                onClick={() => void doDelete()}
                disabled={busy}
                className="flex-1 rounded-lg bg-coral text-night font-medium py-2.5 disabled:opacity-50 transition"
              >
                {busy ? "…" : t("profile.deleteConfirm")}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
