import { clearToken, getToken } from "./auth";

const API_BASE = "";  // 同源调用,Nginx 代理 /api/v1/* 到后端

export class AuthError extends Error {}
export class PermissionError extends Error {}
export class ApiError extends Error {
  constructor(public status: number, msg: string) {
    super(msg);
  }
}

async function _request<T>(path: string, init: RequestInit = {}, withAuth = true): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init.headers as Record<string, string> | undefined),
  };
  if (withAuth) {
    const tok = getToken();
    if (tok) headers["Authorization"] = `Bearer ${tok}`;
  }
  const res = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (res.status === 401) {
    clearToken();
    throw new AuthError("未授权");
  }
  if (res.status === 403) throw new PermissionError("无权限");
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try {
      const j = await res.json();
      if (j?.detail) msg = String(j.detail);
      else if (j?.error) msg = String(j.error);
    } catch {}
    throw new ApiError(res.status, msg);
  }
  return res.json() as Promise<T>;
}

// ============== 认证 ==============

export function requestEmailCode(email: string) {
  return _request<{ status: string; sent: boolean; dev_code?: string }>(
    "/api/v1/auth/email/request",
    { method: "POST", body: JSON.stringify({ email }) },
    false,
  );
}

export function verifyEmailCode(email: string, code: string) {
  return _request<{ token: string; user_id: string; is_new_user: boolean }>(
    "/api/v1/auth/email/verify",
    { method: "POST", body: JSON.stringify({ email, code }) },
    false,
  );
}

// ============== 当前身份 ==============

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
  return _request<MeResponse>("/api/v1/auth/me");
}

// ============== 企业基本信息 ==============

export interface OrgInfo {
  org_id: string;
  name: string;
  industry: string;
  contact_hr_email: string;
  status: string;
  period_end: string;
  seat_quota: number;
  seats_used: number;
}

export function getOrgInfo() {
  return _request<OrgInfo>("/api/v1/org/admin/org_info");
}

// ============== 团队 ==============

export interface TeamSummary {
  team_id: string;
  team_name: string;
  manager_email: string;
  member_count: number;
  created_at: string;
}

export function getTeams() {
  return _request<{ org_id: string; total_members: number; teams: TeamSummary[] }>(
    "/api/v1/org/admin/teams",
  );
}

// ============== 员工导入 ==============

export interface ImportItem {
  email: string;
  line?: number;
  status: "invited" | "already_in_org" | "in_other_org" | "error";
  code?: string;
  team_id?: string;
  email_sent?: boolean;
  error?: string;
  other_org?: string;
}

export interface ImportResult {
  total_rows: number;
  succeeded: number;
  emails_sent: number;
  skipped_already_in_org: number;
  skipped_in_other_org: number;
  parse_errors: string[];
  items: ImportItem[];
}

export function importEmployees(csvText: string, sendEmails = true, expireDays = 14) {
  return _request<ImportResult>("/api/v1/org/admin/employees/import", {
    method: "POST",
    body: JSON.stringify({
      csv_text: csvText,
      send_emails: sendEmails,
      expire_days: expireDays,
    }),
  });
}

// ============== 团队洞察 ==============
type InsufficientData = { status: "insufficient_data"; n: number; k_min: number };
type Ok<T> = { status: "ok"; n: number } & T;
export type InsightResult<T> = Ok<T> | InsufficientData | { status: "error"; error: string; n: number };

export interface OverviewMetrics {
  engagement: {
    active_users: number;
    total_users: number;
    activation_rate: number;
    completion_rate: number | null;
  };
  sleep: {
    avg_se_pct: number | null;
    avg_tst_hours: number | null;
    low_se_ratio: number | null;
    users_with_data: number;
  };
  anxiety: {
    avg_recovery_turns: number | null;
    momentum_distribution: Record<string, number>;
  };
  worry: { top_domain: string | null; total_records: number };
  crisis: { total: number; high: number; medium: number; low: number };
}

export interface SleepMetrics {
  users_with_data: number;
  total_entries: number;
  avg_tst_hours: number | null;
  avg_se_pct: number | null;
  low_se_ratio: number | null;
  short_tst_ratio: number | null;
  se_distribution: Record<string, number>;
}

export interface AnxietyMetrics {
  users_with_data: number;
  avg_recovery_turns: number | null;
  momentum_distribution: Record<string, number>;
}

export interface WorryMetrics {
  users_with_data: number;
  total_worry_records: number;
  distribution_pct: Record<string, number>;
  top_domain: string | null;
  raw_counts: Record<string, number>;
}

export interface CrisisMetrics {
  total: number;
  high: number;
  medium: number;
  low: number;
  weekly_trend: unknown[];
}

export interface EngagementMetrics {
  total_users: number;
  active_users: number;
  activation_rate: number;
  total_sessions: number;
  completion_rate: number | null;
  outcome_distribution: Record<string, number>;
}

function _q(period = "30d", teamId?: string) {
  const p = new URLSearchParams({ period });
  if (teamId) p.set("team_id", teamId);
  return p.toString();
}

export function insightsOverview(period = "30d", teamId?: string) {
  return _request<InsightResult<OverviewMetrics>>(`/api/v1/org/insights/overview?${_q(period, teamId)}`);
}
export function insightsSleep(period = "30d", teamId?: string) {
  return _request<InsightResult<SleepMetrics>>(`/api/v1/org/insights/sleep?${_q(period, teamId)}`);
}
export function insightsAnxiety(period = "30d", teamId?: string) {
  return _request<InsightResult<AnxietyMetrics>>(`/api/v1/org/insights/anxiety?${_q(period, teamId)}`);
}
export function insightsWorry(period = "30d", teamId?: string) {
  return _request<InsightResult<WorryMetrics>>(`/api/v1/org/insights/worry_domains?${_q(period, teamId)}`);
}
export function insightsCrisis(period = "30d", teamId?: string) {
  return _request<InsightResult<CrisisMetrics>>(`/api/v1/org/insights/crisis?${_q(period, teamId)}`);
}
export function insightsEngagement(period = "30d", teamId?: string) {
  return _request<InsightResult<EngagementMetrics>>(`/api/v1/org/insights/engagement?${_q(period, teamId)}`);
}
