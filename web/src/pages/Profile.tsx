import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { clearToken, getUserEmail, getUserId } from "../lib/auth";
import { deleteAccount, AuthError } from "../lib/api";
import LanguageToggle from "../components/LanguageToggle";

export default function Profile() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const email = getUserEmail();
  const userId = getUserId();

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
