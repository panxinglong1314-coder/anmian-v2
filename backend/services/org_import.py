"""
HR 后台 CSV 员工批量导入。

输入:CSV 文本(UTF-8),首行 header,必含 email,可选 name/team_name/department。
处理:
- 为每个有效 email 生成一次性企业邀请码(14 天有效,max_uses=1)
- 若 CSV 指定 team_name 且 team 不存在,自动创建
- 通过 Resend 发送带邀请码的邀请邮件(无 Resend 配置则跳过发信,返 dry_run=True)
- 错误邮件 / 重复邮件 / 已在其它企业的邮件 分类报告,不中断批处理

只允许导入员工到调用方自己的 org_id(由路由层守护)。
"""
from __future__ import annotations

import csv
import io
import os
import re
import time
from typing import List, Dict, Any, Optional, Tuple

from infra.redis_client import redis_client
from services.org import (
    create_invite_code, create_team, list_teams, get_team, get_user_org,
)


_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


def _email_user_id(email: str) -> str:
    import hashlib
    h = hashlib.sha256(email.strip().lower().encode()).hexdigest()[:16]
    return f"em_{h}"


def _normalize_header(s: str) -> str:
    return (s or "").strip().lower().replace("-", "_").replace(" ", "_")


# 列名兼容映射(中英 + 常见变体)
_COL_ALIASES = {
    "email":       {"email", "e_mail", "mail", "邮箱", "邮件", "电子邮箱"},
    "name":        {"name", "full_name", "fullname", "姓名", "名字"},
    "team_name":   {"team", "team_name", "department", "dept", "团队", "部门"},
}


def _detect_column(headers: List[str], target: str) -> Optional[int]:
    aliases = _COL_ALIASES[target]
    for i, h in enumerate(headers):
        if _normalize_header(h) in aliases:
            return i
    return None


def parse_csv(csv_text: str) -> Tuple[List[Dict[str, str]], List[str]]:
    """解析 CSV 文本。Returns (rows, errors)。
    rows 每条: {email, name?, team_name?}"""
    errors: List[str] = []
    if not csv_text or not csv_text.strip():
        return [], ["CSV 内容为空"]

    # 支持 BOM
    if csv_text.startswith("﻿"):
        csv_text = csv_text[1:]

    reader = csv.reader(io.StringIO(csv_text))
    try:
        headers = next(reader)
    except StopIteration:
        return [], ["CSV 没有 header 行"]

    col_email = _detect_column(headers, "email")
    col_name = _detect_column(headers, "name")
    col_team = _detect_column(headers, "team_name")
    if col_email is None:
        return [], [f"CSV 缺少 email 列(headers: {headers})"]

    rows: List[Dict[str, str]] = []
    for lineno, raw in enumerate(reader, start=2):
        if not any(c.strip() for c in raw):
            continue                          # 跳过空行
        email = (raw[col_email] if col_email < len(raw) else "").strip().lower()
        if not email:
            errors.append(f"第 {lineno} 行:邮箱为空")
            continue
        if not _EMAIL_RE.match(email):
            errors.append(f"第 {lineno} 行:邮箱格式无效 ({email})")
            continue
        row = {"email": email, "line": lineno}
        if col_name is not None and col_name < len(raw):
            row["name"] = raw[col_name].strip()
        if col_team is not None and col_team < len(raw):
            row["team_name"] = raw[col_team].strip()
        rows.append(row)
    return rows, errors


def _get_or_create_team(org_id: str, team_name: str) -> Optional[str]:
    """按 team_name 查找该 org 下的 team,没有就创建。返回 team_id。"""
    if not team_name:
        return None
    for tid in list_teams(org_id):
        t = get_team(tid)
        if t and t.get("team_name", "") == team_name:
            return tid
    return create_team(org_id, team_name)


async def _send_invite_email(
    email: str,
    invite_code: str,
    org_name: str,
    sender_name: str = "ZhiMian",
) -> bool:
    """发送邀请邮件。无 RESEND_API_KEY 时返 False。"""
    import httpx
    from infra.settings import settings
    api_key = getattr(settings, "resend_api_key", "") or os.getenv("RESEND_API_KEY", "")
    if not api_key:
        return False

    signup_url = f"https://sleepai.chat/enterprise/join?code={invite_code}"
    subject = f"{org_name} 为你开通了知眠企业版 · 邀请码 {invite_code}"
    body_text = (
        f"你好,\n\n"
        f"{org_name} 为你开通了知眠 (ZhiMian) 企业版 — 一个 AI 助眠陪伴,"
        f"睡前帮你把脑子里转个不停的东西放下来。\n\n"
        f"你的邀请码:{invite_code}\n"
        f"激活页面:{signup_url}\n\n"
        f"重要承诺:你和 AI 的所有对话内容,HR 永远看不到。"
        f"公司只能看到团队层级的匿名聚合数据。\n\n"
        f"邀请码 14 天内有效。\n\n"
        f"— {sender_name}\nhttps://sleepai.chat"
    )
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "from": getattr(settings, "auth_from_email", "ZhiMian <noreply@sleepai.chat>"),
                    "to": [email],
                    "subject": subject,
                    "text": body_text,
                },
            )
            return resp.status_code in (200, 201)
    except Exception as e:
        print(f"[invite email error] {email}: {e}")
        return False


async def import_employees(
    org_id: str,
    csv_text: str,
    org_name: str = "你的公司",
    send_emails: bool = True,
    expire_days: int = 14,
) -> Dict[str, Any]:
    """处理一份 CSV: 生成邀请码 + 发邀请邮件。

    Returns:
        {
          "total_rows": N,
          "succeeded": N,           # 成功生成邀请码(无论邮件是否发出)
          "emails_sent": N,         # 真实发出的邮件数
          "skipped_already_in_org": N,
          "skipped_in_other_org": N,
          "parse_errors": [...],    # CSV 解析错误
          "items": [                # 详细
            {email, status, code?, team_id?, error?}
          ]
        }
    """
    rows, parse_errors = parse_csv(csv_text)
    items: List[Dict[str, Any]] = []
    succeeded = 0
    emails_sent = 0
    skipped_already_in_org = 0
    skipped_in_other_org = 0

    # 预计算 team_name → team_id 映射,避免重复查
    team_id_cache: Dict[str, Optional[str]] = {}

    for row in rows:
        email = row["email"]
        item = {"email": email, "line": row.get("line")}
        # 判断是否已在某 org
        user_id = _email_user_id(email)
        existing_org = get_user_org(user_id)
        if existing_org == org_id:
            item.update({"status": "already_in_org"})
            skipped_already_in_org += 1
            items.append(item)
            continue
        if existing_org and existing_org != org_id:
            item.update({"status": "in_other_org", "other_org": existing_org})
            skipped_in_other_org += 1
            items.append(item)
            continue

        # 解析 team
        team_name = (row.get("team_name") or "").strip()
        team_id: Optional[str] = None
        if team_name:
            if team_name not in team_id_cache:
                try:
                    team_id_cache[team_name] = _get_or_create_team(org_id, team_name)
                except Exception as e:
                    item.update({"status": "error", "error": f"team 创建失败: {e}"})
                    items.append(item)
                    continue
            team_id = team_id_cache[team_name]

        # 生成 1 次性邀请码(每邮件独享)
        try:
            code = create_invite_code(
                org_id, team_id=team_id,
                expire_days=expire_days, max_uses=1,
            )
        except Exception as e:
            item.update({"status": "error", "error": f"邀请码生成失败: {e}"})
            items.append(item)
            continue

        item.update({"status": "invited", "code": code, "team_id": team_id or ""})
        succeeded += 1

        # 发邮件(可选)
        if send_emails:
            sent = await _send_invite_email(email, code, org_name)
            item["email_sent"] = sent
            if sent:
                emails_sent += 1
        items.append(item)

    return {
        "total_rows": len(rows),
        "succeeded": succeeded,
        "emails_sent": emails_sent,
        "skipped_already_in_org": skipped_already_in_org,
        "skipped_in_other_org": skipped_in_other_org,
        "parse_errors": parse_errors,
        "items": items,
    }
