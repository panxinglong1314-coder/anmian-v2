import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { clearToken, getUserEmail, getUserId } from "../lib/auth";
import { deleteAccount, getUsage, getMe, joinOrg, leaveOrg, AuthError, type Usage, type MeResponse } from "../lib/api";
import { setToken } from "../lib/auth";
import LanguageToggle from "../components/LanguageToggle";

export default function Profile() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [usage, setUsage] = useState<Usage | null>(null);
  const [me, setMe] = useState<MeResponse | null>(null);
  const [showJoin, setShowJoin] = useState(false);
  const [inviteInput, setInviteInput] = useState("");
  const [orgMsg, setOrgMsg] = useState<string | null>(null);
  const [confirmLeave, setConfirmLeave] = useState(false);

  const email = getUserEmail();
  const userId = getUserId();

  const refreshMe = () => {
    getMe().then((d) => setMe(d)).catch(() => {});
  };

  useEffect(() => {
    getUsage().then((u) => setUsage(u)).catch(() => {});
    refreshMe();
  }, []);

  const doJoin = async () => {
    if (!inviteInput.trim()) return;
    setBusy(true);
    setOrgMsg(null);
    try {
      const res = await joinOrg(inviteInput.trim());
      setToken(res.token);   // 新 token 携带 org_id
      setInviteInput("");
      setShowJoin(false);
      setOrgMsg(t("profile.org.joinSuccess", { name: res.org.org_name }));
      refreshMe();
    } catch (e) {
      const msg = (e as Error)?.message || t("profile.org.joinError");
      setOrgMsg(msg);
    } finally {
      setBusy(false);
    }
  };

  const doLeave = async () => {
    setBusy(true);
    setOrgMsg(null);
    try {
      const res = await leaveOrg();
      setToken(res.token);
      setConfirmLeave(false);
      setOrgMsg(t("profile.org.leaveSuccess"));
      refreshMe();
    } catch {
      setOrgMsg(t("profile.org.leaveError"));
    } finally {
      setBusy(false);
    }
  };

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

        {/* v2.5 B2B: 企业归属卡片 */}
        {me?.org ? (
          <div className="rounded-xl bg-gold/5 border border-gold/30 px-4 py-4 space-y-3">
            <div className="flex items-start justify-between gap-2">
              <div className="flex-1 min-w-0">
                <div className="text-xs text-gold/80 uppercase tracking-widest">{t("profile.org.title")}</div>
                <div className="text-text text-[15px] font-medium mt-1 truncate">🏢 {me.org.org_name}</div>
                {me.org.team_name && (
                  <div className="text-muted text-xs mt-0.5">· {me.org.team_name}</div>
                )}
              </div>
            </div>
            <div className="text-[11px] text-muted leading-relaxed">
              {t("profile.org.privacyNote")}
            </div>
            <button
              onClick={() => setConfirmLeave(true)}
              className="text-coral/80 text-xs hover:text-coral transition"
            >
              {t("profile.org.leaveButton")}
            </button>
          </div>
        ) : (
          <div className="rounded-xl bg-night-card border border-night-line px-4 py-3">
            {!showJoin ? (
              <button
                onClick={() => setShowJoin(true)}
                className="w-full text-left text-sm text-muted hover:text-text transition"
              >
                🏢 {t("profile.org.joinPrompt")}
              </button>
            ) : (
              <div className="space-y-2">
                <input
                  type="text"
                  value={inviteInput}
                  onChange={(e) => setInviteInput(e.target.value.toUpperCase())}
                  placeholder={t("profile.org.invitePlaceholder")}
                  maxLength={6}
                  className="w-full px-3 py-2 rounded bg-deep border border-night-line text-text font-mono tracking-wider uppercase"
                />
                <div className="flex gap-2">
                  <button
                    onClick={doJoin}
                    disabled={busy || !inviteInput.trim()}
                    className="flex-1 py-2 rounded bg-accent text-deep text-sm disabled:opacity-40 hover:bg-accent/90 transition"
                  >
                    {t("profile.org.joinButton")}
                  </button>
                  <button
                    onClick={() => { setShowJoin(false); setInviteInput(""); setOrgMsg(null); }}
                    className="px-3 py-2 text-sm text-muted hover:text-text transition"
                  >
                    {t("common.back")}
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
        {orgMsg && <p className="text-xs text-center text-muted">{orgMsg}</p>}

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

      {/* Leave org confirm overlay */}
      {confirmLeave && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center px-6 z-50">
          <div className="bg-night-card border border-night-line rounded-2xl p-5 w-full max-w-sm">
            <div className="text-2xl text-center mb-2">🏢</div>
            <h3 className="text-text font-semibold text-center">{t("profile.org.leaveTitle")}</h3>
            <p className="text-muted text-sm mt-2 leading-relaxed">{t("profile.org.leaveWarn")}</p>
            <div className="flex gap-2 mt-5">
              <button
                onClick={() => setConfirmLeave(false)}
                disabled={busy}
                className="flex-1 rounded-lg border border-night-line text-text py-2.5 transition"
              >
                {t("common.back")}
              </button>
              <button
                onClick={() => void doLeave()}
                disabled={busy}
                className="flex-1 rounded-lg bg-coral/80 text-night font-medium py-2.5 disabled:opacity-50 transition"
              >
                {busy ? "…" : t("profile.org.leaveConfirm")}
              </button>
            </div>
          </div>
        </div>
      )}

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
