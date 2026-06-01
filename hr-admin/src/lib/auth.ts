/**
 * HR Admin 鉴权:
 * - 复用员工端的 /api/v1/auth/email/{request,verify}
 * - 验证后拿到的 JWT 若包含 role=hr_admin 才放行进入后台
 * - JWT 存在 localStorage(独立 key,不与 web/ 冲突)
 */
const TOKEN_KEY = "zhimian_hr_token";

export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) || "";
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

export function isLoggedIn(): boolean {
  return !!getToken();
}

/** JWT payload 解析(只 decode,不校验签名 — 校验由后端守门)。*/
export function decodeJwtPayload(): {
  user_id?: string;
  org_id?: string;
  team_id?: string;
  role?: string;
  exp?: number;
} | null {
  const tok = getToken();
  if (!tok) return null;
  try {
    const parts = tok.split(".");
    if (parts.length < 2) return null;
    const payload = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    const padded = payload + "=".repeat((4 - (payload.length % 4)) % 4);
    return JSON.parse(atob(padded));
  } catch {
    return null;
  }
}

export function isHrAdmin(): boolean {
  const p = decodeJwtPayload();
  return !!p && p.role === "hr_admin" && !!p.org_id;
}
