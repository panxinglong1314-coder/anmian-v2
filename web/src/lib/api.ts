import { API_BASE } from "./config";
import { getToken, clearToken, getUserId } from "./auth";

export class AuthError extends Error {}

export interface Quota {
  tier?: string;
  period?: string;
  text_remaining?: number;
  text_limit?: number;
  voice_remaining?: number;
  voice_limit?: number;
}

/** Thrown when the chat stream is blocked by the server-side usage quota (HTTP 403). */
export class QuotaError extends Error {
  quota?: Quota;
  constructor(quota?: Quota) {
    super("quota_reached");
    this.name = "QuotaError";
    this.quota = quota;
  }
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
  if (!res.ok) {
    const data = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(data.detail || `Request failed (${res.status})`);
  }
  return (await res.json()) as T;
}

/** Email magic-code: request a 6-digit code. `dev_code` is present only when no email provider is configured (dev/beta). */
export function requestEmailCode(email: string) {
  return postJson<{ status: string; sent: boolean; dev_code?: string }>(
    "/api/v1/auth/email/request",
    { email }
  );
}

/** Email magic-code: verify the code, returns a JWT. */
export function verifyEmailCode(email: string, code: string) {
  return postJson<{ token: string; user_id: string; is_new_user: boolean }>(
    "/api/v1/auth/email/verify",
    { email, code }
  );
}

/** Google Sign-In: exchange the Google ID token (credential) for our JWT. */
export function googleLogin(credential: string) {
  return postJson<{ token: string; user_id: string; is_new_user: boolean }>(
    "/api/v1/auth/google",
    { credential }
  );
}

/** Authenticated JSON request — injects Authorization: Bearer <jwt>. */
export async function authRequest<T = unknown>(
  path: string,
  options: { method?: string; body?: unknown; signal?: AbortSignal } = {}
): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${API_BASE}${path}`, {
    method: options.method ?? "GET",
    headers,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
    signal: options.signal
  });

  if (res.status === 401) {
    clearToken();
    throw new AuthError("Unauthorized");
  }
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`Request failed (${res.status}): ${detail.slice(0, 200)}`);
  }
  return (await res.json()) as T;
}

export interface ChatEvent {
  event: string;
  data?: unknown;
  message?: string;
  [k: string]: unknown;
}

/**
 * Stream a CBT chat turn from POST /api/v1/chat/cbt/stream (Server-Sent Events).
 * EventSource can't POST, so we read the body stream and parse SSE manually.
 * Calls onEvent for each parsed `data:` line.
 */
export async function streamChat(
  params: { message: string; sessionId: string; locale: string; skipTts?: boolean },
  onEvent: (evt: ChatEvent) => void,
  signal?: AbortSignal
): Promise<void> {
  const token = getToken();
  const res = await fetch(`${API_BASE}/api/v1/chat/cbt/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {})
    },
    body: JSON.stringify({
      message: params.message,
      session_id: params.sessionId,
      locale: params.locale,
      skip_tts: params.skipTts ?? false
    }),
    signal
  });

  if (res.status === 401) {
    clearToken();
    throw new AuthError("Unauthorized");
  }
  if (res.status === 403) {
    const data = (await res.json().catch(() => ({}))) as { detail?: { error?: string; quota?: Quota } };
    if (data?.detail?.error === "quota_reached") throw new QuotaError(data.detail.quota);
    throw new Error(`Chat stream forbidden (403)`);
  }
  if (!res.ok || !res.body) {
    throw new Error(`Chat stream failed (${res.status})`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE frames are separated by blank lines; each "data: ..." line is a JSON payload.
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? ""; // keep incomplete tail
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed.startsWith("data:")) continue;
      const payload = trimmed.slice(5).trim();
      if (!payload) continue;
      try {
        onEvent(JSON.parse(payload) as ChatEvent);
      } catch {
        /* ignore non-JSON keepalives */
      }
    }
  }
}

// ---------- Worries (担忧箱) ----------
export interface WorryRecord {
  id?: string;
  worry_text: string;
  recorded_at: string;
  type?: string;
  domain?: string;
  reviewed?: boolean;
}

export interface WorriesResponse {
  records: WorryRecord[];
  total: number;
  unreviewed_count: number;
}

export function getWorries(): Promise<WorriesResponse> {
  return authRequest<WorriesResponse>(`/api/v1/worries/${encodeURIComponent(getUserId())}?limit=50`);
}

export interface AddWorryResult {
  status: "ok" | "crisis";
  record?: WorryRecord;
  message?: string;
  hotlines?: { name: string; phone?: string; text?: string }[];
}

export function addWorry(text: string, locale: string): Promise<AddWorryResult> {
  return authRequest<AddWorryResult>(`/api/v1/worry`, {
    method: "POST",
    body: { user_id: getUserId(), worry_text: text, locale }
  });
}

// ---------- Sleep diary / SRT ----------
export interface SleepDiary {
  date: string;
  actual_bed_time?: string;
  actual_wake_time?: string;
  sleep_latency_minutes?: number;
  wake_count?: number;
  nap_minutes?: number;
  sleep_quality?: number;
  note?: string;
  tib_minutes?: number;
  tst_minutes?: number;
  se?: number; // fraction 0-1
}

export interface SleepDiaryInput {
  bed_time: string;
  wake_time: string;
  sleep_latency_minutes?: number;
  wake_count?: number;
  nap_minutes?: number;
  quality?: number;
  note?: string;
}

export function submitSleepDiary(d: SleepDiaryInput) {
  return authRequest<{ status: string; tib_minutes: number; tst_minutes: number; se: number; message?: string }>(
    `/api/v1/sleep/diary`,
    { method: "POST", body: d }
  );
}

export function getTodayDiary() {
  return authRequest<{ exists: boolean; date: string; diary: SleepDiary | null }>(`/api/v1/sleep/diary/today`);
}

export interface SleepDashboard {
  has_data?: boolean;
  trend_emoji?: string;
  trend_direction?: string;
  stats?: {
    avg_se?: number; // percent
    avg_tst_hours?: number;
    avg_quality?: number;
    total_records?: number;
    se_level?: string;
    se_message?: string;
  } | null;
}

export function getSleepDashboard(days = 7) {
  return authRequest<SleepDashboard>(`/api/v1/sleep/dashboard?days=${days}`);
}

export function getDiaryHistory(days = 7) {
  return authRequest<{ records: SleepDiary[]; count: number }>(`/api/v1/sleep/diary/history?days=${days}`);
}

// v2.5 B2B: 用户当前身份 + 企业归属
export interface MeResponse {
  user_id: string;
  openid: string;
  role: "user" | "hr_admin";
  org: {
    org_id: string;
    org_name: string;
    industry: string;
    team_id: string;
    team_name: string;
  } | null;
}

export function getMe() {
  return authRequest<MeResponse>(`/api/v1/auth/me`);
}

// 员工绑定企业(已登录用户用邀请码加入)
export function joinOrg(inviteCode: string) {
  return authRequest<{ token: string; user_id: string; org: { org_id: string; org_name: string; team_id: string } }>(`/api/v1/auth/org/join`, {
    method: "POST",
    body: JSON.stringify({ invite_code: inviteCode }),
  });
}

// 员工退订企业
export function leaveOrg() {
  return authRequest<{ token: string; user_id: string; was_in_org: boolean }>(`/api/v1/auth/org/leave`, {
    method: "POST",
  });
}

export interface SleepWindow {
  recommended_bedtime?: string;
  recommended_waketime?: string;
  window_hours?: number;
  message?: string;
  [k: string]: unknown;
}

export function getSleepWindow() {
  return authRequest<SleepWindow>(`/api/v1/sleep/window/${encodeURIComponent(getUserId())}`).catch(() => ({}) as SleepWindow);
}

// ---------- Usage / subscription ----------
export interface Usage {
  tier: string;
  tier_name?: string;
  period: string; // "day" | "month"
  text: { used: number; limit: number; remaining: number; limit_minutes?: number; remaining_minutes?: number };
  voice: { used: number; limit: number; remaining: number; limit_minutes?: number; remaining_minutes?: number };
}

export function getUsage() {
  return authRequest<Usage>(`/api/v1/usage`).catch(() => null);
}

export interface Pricing {
  currency: string;
  yearly_discount: number;
  plans: Record<string, { monthly: number; yearly: number }>;
}

export function getPricing() {
  return authRequest<Pricing>(`/api/v1/pricing`).catch(() => null);
}

// ---------- White noise ----------
export function soundUrl(name: string): string {
  return `${API_BASE}/static/sounds/${name}.mp3`;
}

// ---------- Profile / account ----------
export function getProfile(): Promise<{ nickname: string; avatar_url: string }> {
  return authRequest(`/api/v1/user/profile`);
}

export function deleteAccount(): Promise<{ status: string; keys_deleted?: number }> {
  return authRequest(`/api/v1/user/delete_account`, { method: "POST" });
}

// v2.5 B2B: 提交销售线索(公开端点,无需 auth)
export interface SalesLeadInput {
  company_name: string;
  contact_name?: string;
  contact_email: string;
  contact_phone?: string;
  team_size?: string;
  message?: string;
  locale?: string;
  source?: string;
}

export async function submitSalesLead(input: SalesLeadInput) {
  const res = await fetch(`/api/v1/sales/lead`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (res.status === 429) throw new Error("rate_limited");
  if (!res.ok) {
    let detail = "submit_failed";
    try {
      const j = await res.json();
      detail = j.detail || j.error || detail;
    } catch {}
    throw new Error(detail);
  }
  return res.json() as Promise<{ status: string; lead_id: string; message: string }>;
}

/** Play a base64 mp3 chunk returned by the TTS stream. */
export function playBase64Mp3(b64: string): HTMLAudioElement | null {
  if (!b64) return null;
  const audio = new Audio(`data:audio/mpeg;base64,${b64}`);
  audio.play().catch(() => {});
  return audio;
}
