import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import LanguageDetector from "i18next-browser-languagedetector";
import en from "./locales/en.json";
import zh from "./locales/zh.json";
import { DEFAULT_LOCALE } from "./lib/config";

void i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: {
      en: { translation: en },
      zh: { translation: zh }
    },
    fallbackLng: DEFAULT_LOCALE,
    supportedLngs: ["en", "zh"],
    nonExplicitSupportedLngs: true, // en-US → en
    interpolation: { escapeValue: false },
    detection: {
      // 1) explicit user choice in localStorage, 2) browser language
      order: ["localStorage", "navigator"],
      lookupLocalStorage: "zhimian_locale",
      caches: ["localStorage"]
    }
  });

/** Normalize i18n's resolved language to the backend locale ('en' | 'zh'). */
export function currentLocale(): "en" | "zh" {
  const lng = (i18n.resolvedLanguage || i18n.language || DEFAULT_LOCALE).toLowerCase();
  return lng.startsWith("zh") ? "zh" : "en";
}

export default i18n;
