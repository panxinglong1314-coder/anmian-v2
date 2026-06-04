/**
 * 首次访问 /app 的 60 秒引导。
 *
 * 设计原则:
 * - 短:3 步,每步 1 句话 + 1 个 emoji + 1 句"试试"
 * - 可跳过:右上 × 任何时刻跳过 (不强制完成)
 * - 一次性:localStorage 标记 zhimian_onboarding_v1 已看
 * - 视觉:玻璃拟态卡片 + 暗底 + 金色 accent (与主品牌一致)
 * - 移动端友好:全屏 dialog,大字大按钮
 *
 * 触发:Chat.tsx 在首次挂载且 localStorage 无标记时显示。
 */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

const STORAGE_KEY = "zhimian_onboarding_v1";

interface Step {
  emoji: string;
  titleKey: string;
  bodyKey: string;
  tryKey: string;
}

const STEPS: Step[] = [
  {
    emoji: "🎙️",
    titleKey: "onboarding.s1.title",
    bodyKey: "onboarding.s1.body",
    tryKey: "onboarding.s1.try",
  },
  {
    emoji: "🌊",
    titleKey: "onboarding.s2.title",
    bodyKey: "onboarding.s2.body",
    tryKey: "onboarding.s2.try",
  },
  {
    emoji: "🌙",
    titleKey: "onboarding.s3.title",
    bodyKey: "onboarding.s3.body",
    tryKey: "onboarding.s3.try",
  },
];

interface Props {
  onDone: () => void;
}

export default function OnboardingModal({ onDone }: Props) {
  const { t } = useTranslation();
  const [step, setStep] = useState(0);
  const [closing, setClosing] = useState(false);

  // Esc 关闭
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") finish();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const finish = () => {
    setClosing(true);
    try { localStorage.setItem(STORAGE_KEY, "1"); } catch { /* noop */ }
    // 给一个淡出动画的时间
    setTimeout(onDone, 220);
  };

  const next = () => {
    if (step >= STEPS.length - 1) finish();
    else setStep(step + 1);
  };

  const back = () => {
    if (step > 0) setStep(step - 1);
  };

  const current = STEPS[step];
  const isLast = step === STEPS.length - 1;

  return (
    <div
      className={`fixed inset-0 z-[60] flex items-center justify-center p-5 transition-opacity duration-200 ${
        closing ? "opacity-0" : "opacity-100"
      }`}
      style={{ background: "rgba(8, 12, 24, 0.72)", backdropFilter: "blur(8px)" }}
      role="dialog"
      aria-modal="true"
      aria-labelledby="onboarding-title"
    >
      <div
        className="relative w-full max-w-md rounded-3xl px-7 pt-6 pb-7"
        style={{
          background: "rgba(20, 28, 56, 0.85)",
          border: "1px solid rgba(245, 200, 105, 0.22)",
          boxShadow:
            "0 30px 80px rgba(0,0,0,0.55), inset 0 1px 0 rgba(255,224,168,0.12)",
          backdropFilter: "blur(28px) saturate(160%)",
        }}
      >
        {/* 跳过 */}
        <button
          onClick={finish}
          aria-label={t("onboarding.skip")}
          className="absolute top-3 right-4 text-2xl leading-none transition"
          style={{ color: "rgba(245, 232, 200, 0.5)" }}
        >
          ×
        </button>

        {/* 进度点 */}
        <div className="flex items-center justify-center gap-1.5 mb-6 mt-1">
          {STEPS.map((_, i) => (
            <span
              key={i}
              className="block rounded-full transition-all"
              style={{
                width: i === step ? 22 : 6,
                height: 6,
                background: i === step
                  ? "linear-gradient(90deg, #f5c869, #ffd57a)"
                  : "rgba(245, 232, 200, 0.22)",
              }}
            />
          ))}
        </div>

        {/* 主体 */}
        <div className="text-center">
          <div className="text-6xl mb-4" aria-hidden="true">{current.emoji}</div>
          <h2
            id="onboarding-title"
            className="text-xl font-bold mb-3"
            style={{ color: "#f5e8c8", letterSpacing: "0.02em" }}
          >
            {t(current.titleKey)}
          </h2>
          <p
            className="text-sm leading-relaxed mb-4 px-1"
            style={{ color: "rgba(245, 232, 200, 0.78)" }}
          >
            {t(current.bodyKey)}
          </p>
          <div
            className="rounded-xl px-4 py-3 text-sm font-medium"
            style={{
              background: "rgba(245, 200, 105, 0.10)",
              border: "1px solid rgba(245, 200, 105, 0.22)",
              color: "#ffd57a",
            }}
          >
            💡 {t(current.tryKey)}
          </div>
        </div>

        {/* 按钮区 */}
        <div className="flex items-center justify-between mt-7">
          <button
            onClick={back}
            disabled={step === 0}
            className="text-sm transition disabled:opacity-30"
            style={{ color: "rgba(245, 232, 200, 0.6)" }}
          >
            ← {t("onboarding.back")}
          </button>
          <button
            onClick={next}
            className="rounded-full px-7 py-2.5 font-semibold text-sm transition"
            style={{
              background: "linear-gradient(135deg, #f5c869, #c9956a)",
              color: "#1a2238",
              boxShadow: "0 6px 22px rgba(245, 200, 105, 0.32)",
              letterSpacing: "0.04em",
            }}
          >
            {isLast ? t("onboarding.start") : t("onboarding.next")}
          </button>
        </div>

        {/* 底部 hint */}
        <p
          className="text-[11px] text-center mt-4"
          style={{ color: "rgba(245, 232, 200, 0.35)" }}
        >
          {t("onboarding.footnote")}
        </p>
      </div>
    </div>
  );
}

/** 同步查询是否已看过 (供 Chat.tsx 决定要不要挂载) */
export function shouldShowOnboarding(): boolean {
  try {
    return !localStorage.getItem(STORAGE_KEY);
  } catch {
    return false;
  }
}
