// API base. In dev, Vite proxies /api → backend (see vite.config.ts), so "" works.
// In prod, set VITE_API_BASE to the backend origin if not same-origin.
export const API_BASE = import.meta.env.VITE_API_BASE ?? "";

// Google Sign-In Web OAuth Client ID (xxx.apps.googleusercontent.com).
// Empty → the "Continue with Google" button is hidden.
export const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID ?? "";

export const SUPPORTED_LOCALES = ["en", "zh"] as const;
export type Locale = (typeof SUPPORTED_LOCALES)[number];

export const DEFAULT_LOCALE: Locale = "en";
