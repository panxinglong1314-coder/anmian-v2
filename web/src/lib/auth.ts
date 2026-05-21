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
