import { useTranslation } from "react-i18next";
import { currentLocale } from "../i18n";

export default function LangToggle() {
  const { i18n } = useTranslation();
  const locale = currentLocale();
  const next = locale === "zh" ? "en" : "zh";
  return (
    <button
      onClick={() => i18n.changeLanguage(next)}
      className="text-muted hover:text-text transition"
      title="Language / 语言"
    >
      {locale === "zh" ? "EN" : "中"}
    </button>
  );
}
