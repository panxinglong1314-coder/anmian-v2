import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import LanguageDetector from "i18next-browser-languagedetector";
import en from "./locales/en.json";
import zh from "./locales/zh.json";

void i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: {
      en: { translation: en },
      zh: { translation: zh },
    },
    fallbackLng: "zh",
    supportedLngs: ["en", "zh"],
    nonExplicitSupportedLngs: true,
    interpolation: { escapeValue: false },
    detection: {
      order: ["localStorage", "navigator"],
      lookupLocalStorage: "zhimian_hr_locale",
      caches: ["localStorage"],
    },
  });

export function currentLocale(): "en" | "zh" {
  const lng = (i18n.resolvedLanguage || i18n.language || "zh").toLowerCase();
  return lng.startsWith("zh") ? "zh" : "en";
}

export default i18n;
