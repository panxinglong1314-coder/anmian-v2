// JWT token storage. Mirrors the miniprogram's app.getToken() pattern.
// MVP: token is obtained via a dev paste-in screen (see pages/Login.tsx).
// TODO (next sub-task): replace with email magic-link + Apple + Google sign-in,
// backed by new /api/v1/auth/email|oauth endpoints. user_id will be em_/apple_/google_*.

const TOKEN_KEY = "zhimian_jwt";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token.trim());
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

export function isLoggedIn(): boolean {
  return !!getToken();
}

interface JwtPayload {
  user_id?: string;
  openid?: string;
  exp?: number;
}

/** Decode the JWT payload (no signature check — display/routing only). */
export function getJwtPayload(): JwtPayload | null {
  const t = getToken();
  if (!t) return null;
  try {
    const seg = t.split(".")[1];
    const json = atob(seg.replace(/-/g, "+").replace(/_/g, "/"));
    return JSON.parse(json) as JwtPayload;
  } catch {
    return null;
  }
}

export function getUserId(): string {
  return getJwtPayload()?.user_id || "me";
}

/** For email-auth users, openid is the email address. */
export function getUserEmail(): string | null {
  const oid = getJwtPayload()?.openid || "";
  return oid.includes("@") ? oid : null;
}
