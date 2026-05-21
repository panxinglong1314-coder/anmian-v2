import { useTranslation } from "react-i18next";

/** Manual language override. Persists to localStorage via i18next-browser-languagedetector. */
export default function LanguageToggle() {
  const { i18n } = useTranslation();
  const current = (i18n.resolvedLanguage || "en").startsWith("zh") ? "zh" : "en";

  const toggle = () => {
    const next = current === "en" ? "zh" : "en";
    void i18n.changeLanguage(next);
  };

  return (
    <button
      onClick={toggle}
      className="text-muted text-xs px-2 py-1 rounded border border-night-line hover:text-text transition"
      aria-label="Toggle language"
    >
      {current === "en" ? "中文" : "EN"}
    </button>
  );
}
