/**
 * /enterprise/register — HR 自助注册
 *
 * 流程:邮箱 → 邮件验证码 → 验证码 + 邀请码 → 后端一站式
 *   POST /api/v1/auth/org/register {email, code, invite_code}
 *   → 返回带 org_id 的 JWT (邀请码若为 hr_admin 类型则 role=hr_admin)
 *   → 写本地 token
 *   → role=hr_admin 跳 /hr-admin/,否则跳 /app
 *
 * 设计要点:
 * - 复用 MarketingShell 视频背景 (App.tsx 已挂在 <MarketingShell> 路由组下)
 * - 邀请码 6 位 alnum,实时大写 + 限长
 * - dev_code 在无邮件服务环境下回显,便于本地/灰度测试
 * - 错误来自后端 detail:邀请码无效 / 验证码错 / 席位满 / 已在其它 org
 */
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { setToken } from "../lib/auth";
import { requestEmailCode, registerOrg } from "../lib/api";
import LanguageToggle from "../components/LanguageToggle";

type Step = "email" | "verify";

export default function EnterpriseRegister() {
  const { t } = useTranslation();
  const [params] = useSearchParams();

  const [step, setStep] = useState<Step>("email");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  // 邀请码可以从 URL 预填: /enterprise/register?invite=ACME01
  const [invite, setInvite] = useState((params.get("invite") || "").toUpperCase());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [devCode, setDevCode] = useState<string | null>(null);

  const validEmail = email.includes("@") && email.includes(".");
  const validInvite = /^[A-Z0-9]{4,12}$/.test(invite);

  const sendCode = async () => {
    setError(null);
    setBusy(true);
    try {
      const r = await requestEmailCode(email.trim().toLowerCase());
      setDevCode(r.dev_code ?? null);
      setStep("verify");
    } catch (e) {
      setError(e instanceof Error ? e.message : t("entReg.errSendCode"));
    } finally {
      setBusy(false);
    }
  };

  const register = async () => {
    setError(null);
    setBusy(true);
    try {
      const r = await registerOrg(email, code, invite);
      setToken(r.token);
      // role 在 token 里;为简单起见直接尝试跳 hr-admin,失败再回 /app
      // hr-admin 自己会校验角色,不是 HR 会被 reason=no_hr_role 弹回
      window.location.assign("/hr-admin/");
    } catch (e) {
      setError(e instanceof Error ? e.message : t("entReg.errRegister"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen flex flex-col items-center justify-center px-6 relative">
      {/* 背景视频由 MarketingShell 全局提供 */}
      <Link
        to="/enterprise"
        className="absolute top-4 left-4 flex items-center gap-1.5 text-sm text-muted hover:text-text transition"
      >
        <span>←</span>
        <span className="font-semibold">{t("entReg.backToEnterprise")}</span>
      </Link>
      <div className="absolute top-4 right-4">
        <LanguageToggle />
      </div>

      <div className="text-5xl mb-4">🏢</div>
      <h1 className="text-2xl font-semibold text-accent">{t("entReg.title")}</h1>
      <p className="text-muted mt-2 mb-8 text-center max-w-md text-sm leading-relaxed">
        {t("entReg.subtitle")}
      </p>

      <div className="w-full max-w-sm space-y-3">
        {step === "email" && (
          <>
            <label className="block">
              <span className="text-[11px] uppercase tracking-widest text-muted">
                {t("entReg.emailLabel")}
              </span>
              <input
                type="email"
                autoComplete="email"
                value={email}
                onChange={(e) => { setEmail(e.target.value); setError(null); }}
                onKeyDown={(e) => e.key === "Enter" && validEmail && void sendCode()}
                placeholder={t("entReg.emailPlaceholder")}
                className="mt-1 w-full rounded-lg bg-night-card border border-night-line px-3 py-2.5 text-sm text-text placeholder:text-muted/60 focus:outline-none focus:border-accent"
              />
            </label>
            <button
              onClick={() => void sendCode()}
              disabled={busy || !validEmail}
              className="w-full rounded-lg bg-accent text-night font-medium py-2.5 hover:opacity-90 disabled:opacity-40 transition"
            >
              {busy ? t("entReg.sending") : t("entReg.sendCode")}
            </button>
            <p className="text-muted/60 text-[11px] text-center leading-relaxed">
              {t("entReg.workEmailHint")}
            </p>
          </>
        )}

        {step === "verify" && (
          <>
            <p className="text-muted text-xs text-center">
              {t("entReg.codeSentTo")} <span className="text-text">{email}</span>
            </p>

            <label className="block">
              <span className="text-[11px] uppercase tracking-widest text-muted">
                {t("entReg.codeLabel")}
              </span>
              <input
                inputMode="numeric"
                maxLength={6}
                value={code}
                onChange={(e) => { setCode(e.target.value.replace(/\D/g, "")); setError(null); }}
                placeholder="••••••"
                className="mt-1 w-full text-center tracking-[0.5em] text-lg rounded-lg bg-night-card border border-night-line px-3 py-2.5 text-text placeholder:text-muted/40 focus:outline-none focus:border-accent"
              />
            </label>
            {devCode && (
              <p className="text-muted/70 text-[11px] text-center">
                {t("entReg.devCode")}: <span className="text-accent font-mono">{devCode}</span>
              </p>
            )}

            <label className="block">
              <span className="text-[11px] uppercase tracking-widest text-muted">
                {t("entReg.inviteLabel")}
              </span>
              <input
                value={invite}
                onChange={(e) => {
                  setInvite(e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 12));
                  setError(null);
                }}
                onKeyDown={(e) => e.key === "Enter" && code.length === 6 && validInvite && void register()}
                placeholder="ACME01"
                className="mt-1 w-full font-mono tracking-widest text-base rounded-lg bg-night-card border border-night-line px-3 py-2.5 text-text placeholder:text-muted/40 focus:outline-none focus:border-accent"
                autoCapitalize="characters"
                autoCorrect="off"
                spellCheck={false}
              />
            </label>
            <p className="text-muted/60 text-[11px] leading-relaxed">
              {t("entReg.inviteHint")}
            </p>

            <button
              onClick={() => void register()}
              disabled={busy || code.length !== 6 || !validInvite}
              className="w-full rounded-lg bg-accent text-night font-medium py-2.5 hover:opacity-90 disabled:opacity-40 transition"
            >
              {busy ? t("entReg.registering") : t("entReg.register")}
            </button>
            <button
              onClick={() => {
                setStep("email"); setCode(""); setError(null);
              }}
              className="w-full text-muted text-xs py-1 hover:text-text transition"
            >
              {t("entReg.changeEmail")}
            </button>
          </>
        )}

        {error && <p className="text-coral text-xs text-center">{error}</p>}

        <div className="pt-4 border-t border-night-line/40 mt-4">
          <p className="text-muted/60 text-[11px] text-center leading-relaxed">
            {t("entReg.consentNote")}{" "}
            <Link to="/privacy" className="text-accent hover:underline">{t("entReg.privacy")}</Link>
            {" · "}
            <Link to="/terms" className="text-accent hover:underline">{t("entReg.terms")}</Link>
          </p>
          <p className="text-muted/50 text-[11px] text-center mt-2">
            {t("entReg.noInvite")}{" "}
            <Link to="/enterprise#contact" className="text-accent hover:underline">
              {t("entReg.contactSales")}
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
