import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { setToken } from "../lib/auth";
import { requestEmailCode, verifyEmailCode, googleLogin } from "../lib/api";
import { GOOGLE_CLIENT_ID } from "../lib/config";
import LanguageToggle from "../components/LanguageToggle";

type Step = "email" | "code";

export default function Login() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [step, setStep] = useState<Step>("email");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [devCode, setDevCode] = useState<string | null>(null);
  const gbtnRef = useRef<HTMLDivElement>(null);

  // Google Identity Services — load script + render button when configured.
  useEffect(() => {
    if (!GOOGLE_CLIENT_ID) return;
    const onCredential = async (resp: { credential: string }) => {
      setError(null);
      setBusy(true);
      try {
        const r = await googleLogin(resp.credential);
        setToken(r.token);
        navigate("/app", { replace: true });
      } catch {
        setError(t("login.error"));
        setBusy(false);
      }
    };
    const init = () => {
      window.google?.accounts.id.initialize({ client_id: GOOGLE_CLIENT_ID, callback: onCredential });
      window.google?.accounts.id.renderButton(gbtnRef.current, {
        theme: "outline",
        size: "large",
        width: 320,
        text: "continue_with",
        shape: "pill"
      });
    };
    if (window.google) {
      init();
      return;
    }
    const script = document.createElement("script");
    script.src = "https://accounts.google.com/gsi/client";
    script.async = true;
    script.onload = init;
    document.body.appendChild(script);
    return () => {
      script.remove();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const sendCode = async () => {
    setError(null);
    setBusy(true);
    try {
      const r = await requestEmailCode(email.trim());
      setDevCode(r.dev_code ?? null);
      setStep("code");
    } catch (e) {
      setError(e instanceof Error ? e.message : t("login.error"));
    } finally {
      setBusy(false);
    }
  };

  const verify = async () => {
    setError(null);
    setBusy(true);
    try {
      const r = await verifyEmailCode(email.trim(), code.trim());
      setToken(r.token);
      navigate("/app", { replace: true });
    } catch (e) {
      setError(e instanceof Error ? e.message : t("login.error"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-full flex flex-col items-center justify-center px-6 relative">
      {/* 背景视频由 MarketingShell 全局提供 */}
      <Link
        to="/"
        className="absolute top-4 left-4 flex items-center gap-1.5 text-sm text-muted hover:text-text transition"
      >
        <span>←</span>
        <span className="font-semibold">🌙 {t("app.name")}</span>
      </Link>
      <div className="absolute top-4 right-4">
        <LanguageToggle />
      </div>
      <div className="text-5xl mb-4">🌙</div>
      <h1 className="text-2xl font-semibold text-accent">{t("login.title")}</h1>
      <p className="text-muted mt-2 mb-8 text-center">{t("login.subtitle")}</p>

      <div className="w-full max-w-sm space-y-3">
        {/* Google Sign-In (hidden until VITE_GOOGLE_CLIENT_ID is set) */}
        {GOOGLE_CLIENT_ID && (
          <>
            <div ref={gbtnRef} className="flex justify-center" />
            <div className="flex items-center gap-3 py-1">
              <div className="flex-1 h-px bg-night-line" />
              <span className="text-muted/60 text-xs">{t("login.or")}</span>
              <div className="flex-1 h-px bg-night-line" />
            </div>
          </>
        )}

        {step === "email" && (
          <>
            <input
              type="email"
              autoComplete="email"
              value={email}
              onChange={(e) => {
                setEmail(e.target.value);
                setError(null);
              }}
              onKeyDown={(e) => e.key === "Enter" && email.includes("@") && void sendCode()}
              placeholder={t("login.emailPlaceholder")}
              className="w-full rounded-lg bg-night-card border border-night-line px-3 py-2.5 text-sm text-text placeholder:text-muted/60 focus:outline-none focus:border-accent"
            />
            <button
              onClick={() => void sendCode()}
              disabled={busy || !email.includes("@")}
              className="w-full rounded-lg bg-accent text-night font-medium py-2.5 hover:opacity-90 disabled:opacity-40 transition"
            >
              {busy ? t("login.sending") : t("login.sendCode")}
            </button>
            <p className="text-muted/60 text-[11px] text-center leading-relaxed">{t("login.emailHint")}</p>
          </>
        )}

        {step === "code" && (
          <>
            <p className="text-muted text-xs text-center">
              {t("login.codeSentTo")} <span className="text-text">{email}</span>
            </p>
            <input
              inputMode="numeric"
              maxLength={6}
              value={code}
              onChange={(e) => {
                setCode(e.target.value.replace(/\D/g, ""));
                setError(null);
              }}
              onKeyDown={(e) => e.key === "Enter" && code.length === 6 && void verify()}
              placeholder="••••••"
              className="w-full text-center tracking-[0.5em] text-lg rounded-lg bg-night-card border border-night-line px-3 py-2.5 text-text placeholder:text-muted/40 focus:outline-none focus:border-accent"
            />
            {devCode && (
              <p className="text-muted/70 text-[11px] text-center">
                {t("login.devCode")}: <span className="text-accent font-mono">{devCode}</span>
              </p>
            )}
            <button
              onClick={() => void verify()}
              disabled={busy || code.length !== 6}
              className="w-full rounded-lg bg-accent text-night font-medium py-2.5 hover:opacity-90 disabled:opacity-40 transition"
            >
              {busy ? t("login.verifying") : t("login.verify")}
            </button>
            <button
              onClick={() => {
                setStep("email");
                setCode("");
                setError(null);
              }}
              className="w-full text-muted text-xs py-1 hover:text-text transition"
            >
              {t("login.changeEmail")}
            </button>
          </>
        )}

        {error && <p className="text-coral text-xs text-center">{error}</p>}
        <p className="text-muted/60 text-[11px] leading-relaxed text-center pt-2">
          {t("login.providerNote")}
        </p>
      </div>
    </div>
  );
}
