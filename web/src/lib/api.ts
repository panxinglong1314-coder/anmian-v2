import { API_BASE } from "./config";
import { getToken, clearToken, getUserId } from "./auth";

export class AuthError extends Error {}

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

// ---------- Profile / account ----------
export function getProfile(): Promise<{ nickname: string; avatar_url: string }> {
  return authRequest(`/api/v1/user/profile`);
}

export function deleteAccount(): Promise<{ status: string; keys_deleted?: number }> {
  return authRequest(`/api/v1/user/delete_account`, { method: "POST" });
}

/** Play a base64 mp3 chunk returned by the TTS stream. */
export function playBase64Mp3(b64: string): HTMLAudioElement | null {
  if (!b64) return null;
  const audio = new Audio(`data:audio/mpeg;base64,${b64}`);
  audio.play().catch(() => {});
  return audio;
}
