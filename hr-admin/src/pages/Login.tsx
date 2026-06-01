import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { requestEmailCode, verifyEmailCode } from "../lib/api";
import { setToken, decodeJwtPayload, clearToken } from "../lib/auth";
import LangToggle from "../components/LangToggle";

export default function Login() {
  const { t } = useTranslation();
  const nav = useNavigate();
  const [params] = useSearchParams();
  const reason = params.get("reason");

  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [step, setStep] = useState<"email" | "code">("email");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [devCode, setDevCode] = useState<string | null>(null);

  useEffect(() => {
    if (reason === "no_hr_role") setErr(t("login.errNoHrRole"));
  }, [reason, t]);

  const onRequest = async () => {
    setErr(null);
    setBusy(true);
    try {
      const res = await requestEmailCode(email.trim().toLowerCase());
      setDevCode(res.dev_code || null);
      setStep("code");
    } catch (e) {
      setErr((e as Error).message || t("login.errGeneric"));
    } finally {
      setBusy(false);
    }
  };

  const onVerify = async () => {
    setErr(null);
    setBusy(true);
    try {
      const res = await verifyEmailCode(email.trim().toLowerCase(), code.trim());
      setToken(res.token);
      // 检查 role
      const p = decodeJwtPayload();
      if (!p || p.role !== "hr_admin" || !p.org_id) {
        clearToken();
        setErr(t("login.errNoHrRole"));
        return;
      }
      nav("/", { replace: true });
    } catch (e) {
      setErr((e as Error).message || t("login.errGeneric"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="h-full flex items-center justify-center bg-bg px-6">
      <div className="absolute top-4 right-6">
        <LangToggle />
      </div>
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <div className="text-5xl mb-3">📊</div>
          <h1 className="text-2xl font-bold text-text">{t("login.title")}</h1>
          <p className="text-muted text-sm mt-2 leading-relaxed">{t("login.subtitle")}</p>
        </div>

        <div className="bg-card/60 border border-line rounded-2xl p-6 space-y-4">
          {step === "email" ? (
            <>
              <label className="block">
                <span className="text-xs text-muted">{t("login.emailLabel")}</span>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="hr@yourcompany.com"
                  className="w-full mt-1 px-3 py-2.5 rounded bg-bg border border-line text-text outline-none focus:border-accent transition"
                  onKeyDown={(e) => e.key === "Enter" && email && void onRequest()}
                />
              </label>
              <button
                onClick={() => void onRequest()}
                disabled={busy || !email}
                className="w-full py-2.5 rounded bg-accent text-bg font-medium disabled:opacity-40 hover:bg-accent/90 transition"
              >
                {busy ? "…" : t("login.sendCode")}
              </button>
            </>
          ) : (
            <>
              <p className="text-sm text-muted">{t("login.codeSentTo")} <span className="text-text">{email}</span></p>
              {devCode && (
                <p className="text-xs text-warn bg-warn/10 border border-warn/30 rounded px-3 py-2">
                  {t("login.devCode")}: <span className="font-mono">{devCode}</span>
                </p>
              )}
              <label className="block">
                <span className="text-xs text-muted">{t("login.codeLabel")}</span>
                <input
                  type="text"
                  inputMode="numeric"
                  value={code}
                  onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                  placeholder="000000"
                  maxLength={6}
                  className="w-full mt-1 px-3 py-2.5 rounded bg-bg border border-line text-text outline-none focus:border-accent transition font-mono tracking-widest text-center"
                  onKeyDown={(e) => e.key === "Enter" && code.length === 6 && void onVerify()}
                />
              </label>
              <div className="flex gap-2">
                <button
                  onClick={() => setStep("email")}
                  className="px-4 py-2.5 rounded border border-line text-muted hover:text-text transition"
                >
                  {t("common.back")}
                </button>
                <button
                  onClick={() => void onVerify()}
                  disabled={busy || code.length < 6}
                  className="flex-1 py-2.5 rounded bg-accent text-bg font-medium disabled:opacity-40 hover:bg-accent/90 transition"
                >
                  {busy ? "…" : t("login.verify")}
                </button>
              </div>
            </>
          )}

          {err && <p className="text-bad text-sm text-center">{err}</p>}
        </div>

        <p className="text-xs text-muted text-center mt-6 leading-relaxed">
          {t("login.noteFooter")}
        </p>
      </div>
    </div>
  );
}
