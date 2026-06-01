"""
B2B 月度报告生成 (HTML → PDF via weasyprint)。

设计要点:
- 完全复用 services/org_insights.py 的 6 个 metric_fn
- 模板:static/templates/monthly_report.html (Jinja2)
- PDF 通过 weasyprint 渲染
- 缓存:Redis key org:report:{org_id}:{YYYY-MM},命中即返,
  失效条件:模板/数据变更人为 redis-cli del 即可
- 仅 hr_admin 角色可调,跟 insights 一样

输出:
  bytes(PDF 数据) — 由路由层包装成 StreamingResponse
"""
from __future__ import annotations

import json
import io
import logging
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional, Dict, Any

from infra.redis_client import redis_client


TEMPLATES_DIR = Path(__file__).parent.parent.parent / "static" / "templates"
DEFAULT_TEMPLATE = "monthly_report.html"
# Redis 缓存 PDF base64 — 7 天足够当月再生成
CACHE_TTL_SECONDS = 7 * 24 * 3600


def _cache_key(org_id: str, year_month: str) -> str:
    return f"org:report:{org_id}:{year_month}"


def _render_html(context: Dict[str, Any]) -> str:
    """用 Jinja2 渲染模板。无 Jinja2 则用极简 str.format 兜底。"""
    template_path = TEMPLATES_DIR / DEFAULT_TEMPLATE
    if not template_path.exists():
        raise FileNotFoundError(f"template not found: {template_path}")
    raw = template_path.read_text(encoding="utf-8")
    try:
        from jinja2 import Environment, BaseLoader, select_autoescape
        env = Environment(
            loader=BaseLoader(),
            autoescape=select_autoescape(["html"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        tpl = env.from_string(raw)
        return tpl.render(**context)
    except ImportError:
        # 极简降级:仅替换 {{ var }} 不支持循环
        out = raw
        for k, v in context.items():
            out = out.replace("{{ " + k + " }}", str(v))
        return out


def _html_to_pdf(html: str) -> bytes:
    """weasyprint HTML → PDF bytes。"""
    try:
        from weasyprint import HTML
    except ImportError as e:
        raise RuntimeError(
            "weasyprint not installed. Run: pip install weasyprint>=60.0"
        ) from e
    pdf_io = io.BytesIO()
    HTML(string=html, base_url=str(TEMPLATES_DIR)).write_pdf(pdf_io)
    return pdf_io.getvalue()


def _format_pct(v: Optional[float], suffix: str = "%") -> str:
    if v is None:
        return "—"
    return f"{v}{suffix}"


def _format_num(v: Optional[float]) -> str:
    if v is None:
        return "—"
    return str(v)


def _format_distro(d: Optional[Dict[str, int]]) -> str:
    """SE 分布之类的 dict → HTML 段(模板里 |safe)。"""
    if not d:
        return '<span class="muted">—</span>'
    total = sum(d.values()) or 1
    rows = []
    for label, n in d.items():
        pct = (n / total) * 100
        rows.append(
            f'<div class="bar-row">'
            f'<span class="bar-label">{label}</span>'
            f'<span class="bar-track"><span class="bar-fill" style="width:{pct:.1f}%"></span></span>'
            f'<span class="bar-value">{n}</span>'
            f'</div>'
        )
    return "\n".join(rows)


_DOMAIN_LABELS_ZH = {
    "work": "工作压力", "relationship": "人际关系", "health": "健康担忧",
    "finance": "财务压力", "study": "学业压力", "family": "家庭关系",
    "future": "未来焦虑", "general": "其他",
}
_DOMAIN_LABELS_EN = {
    "work": "Work", "relationship": "Relationships", "health": "Health",
    "finance": "Finance", "study": "Study", "family": "Family",
    "future": "Future", "general": "Other",
}


def _format_worry_top(top: Optional[str], locale: str = "zh") -> str:
    if not top:
        return "—"
    labels = _DOMAIN_LABELS_EN if locale == "en" else _DOMAIN_LABELS_ZH
    return labels.get(top, top)


def _build_period_label(year_month: str, locale: str = "zh") -> str:
    """'2026-05' → '2026 年 5 月' / 'May 2026'."""
    try:
        y, m = year_month.split("-")
        y, m = int(y), int(m)
        if locale == "en":
            import calendar
            return f"{calendar.month_name[m]} {y}"
        return f"{y} 年 {m} 月"
    except Exception:
        return year_month


def generate_monthly_report(
    org_id: str,
    year_month: str,
    team_id: Optional[str] = None,
    locale: str = "zh",
    use_cache: bool = True,
) -> bytes:
    """生成月报 PDF bytes。

    year_month: 'YYYY-MM' 格式。若是当前月,数据可能未完整。
    """
    if not _valid_ym(year_month):
        raise ValueError(f"invalid year_month: {year_month} (expect YYYY-MM)")

    # 缓存
    if use_cache and redis_client:
        try:
            cached = redis_client.get(_cache_key(org_id, year_month))
            if cached:
                import base64
                raw = cached.decode() if isinstance(cached, bytes) else cached
                return base64.b64decode(raw)
        except Exception:
            pass

    # 算时间窗
    period_start, period_end = _ym_to_range(year_month)
    cutoff = period_start  # insights 函数用 cutoff 起点

    # 拉数据
    from services.org_insights import (
        get_users_for_scope, metric_overview, metric_sleep,
        metric_anxiety, metric_worry_domains, metric_crisis,
        metric_engagement, DEFAULT_K_MIN,
    )
    from services.org import get_org, get_team

    org = get_org(org_id)
    if not org:
        raise ValueError(f"org {org_id} not found")

    user_ids = get_users_for_scope(org_id, team_id)
    n = len(user_ids)
    insufficient = n < DEFAULT_K_MIN

    metrics = {}
    if not insufficient:
        try:
            metrics["sleep"] = metric_sleep(user_ids, cutoff)
            metrics["anxiety"] = metric_anxiety(user_ids, cutoff)
            metrics["worry"] = metric_worry_domains(user_ids, cutoff)
            metrics["crisis"] = metric_crisis(user_ids, cutoff, org_id)
            metrics["engagement"] = metric_engagement(user_ids, cutoff, org_id)
        except Exception as e:
            logging.warning(f"[org_report] metric compute partial fail: {e}")

    team = get_team(team_id) if team_id else None
    scope_label = team["team_name"] if team else (
        ("All teams" if locale == "en" else "全公司")
    )

    # 构造模板上下文
    ctx = {
        "locale": locale,
        "org_name": org.get("name", ""),
        "industry": org.get("industry", ""),
        "scope_label": scope_label,
        "period_label": _build_period_label(year_month, locale),
        "year_month": year_month,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "n_users": n,
        "k_min": DEFAULT_K_MIN,
        "insufficient": insufficient,
        # i18n labels
        "labels": _labels(locale),
    }
    if not insufficient and metrics:
        sleep = metrics.get("sleep", {})
        anx = metrics.get("anxiety", {})
        worry = metrics.get("worry", {})
        crisis = metrics.get("crisis", {})
        eng = metrics.get("engagement", {})
        ctx.update({
            "engagement_active": eng.get("active_users", 0),
            "engagement_total": eng.get("total_users", n),
            "engagement_activation": _format_pct(eng.get("activation_rate")),
            "engagement_completion": _format_pct(eng.get("completion_rate")),
            "engagement_sessions": _format_num(eng.get("total_sessions", 0)),
            "sleep_se": _format_pct(sleep.get("avg_se_pct")),
            "sleep_tst": _format_pct(sleep.get("avg_tst_hours"), "h"),
            "sleep_low_se": _format_pct(sleep.get("low_se_ratio")),
            "sleep_short_tst": _format_pct(sleep.get("short_tst_ratio")),
            "sleep_users": sleep.get("users_with_data", 0),
            "sleep_distribution_html": _format_distro(sleep.get("se_distribution")),
            "anx_recovery": _format_num(anx.get("avg_recovery_turns")),
            "anx_users": anx.get("users_with_data", 0),
            "anx_momentum_html": _format_distro(anx.get("momentum_distribution")),
            "worry_top": _format_worry_top(worry.get("top_domain"), locale),
            "worry_total": worry.get("total_worry_records", 0),
            "worry_distribution_html": _format_distro(
                {_DOMAIN_LABELS_EN.get(k, k) if locale == "en" else _DOMAIN_LABELS_ZH.get(k, k): v
                 for k, v in (worry.get("raw_counts") or {}).items()}
            ),
            "crisis_high": crisis.get("high", 0),
            "crisis_medium": crisis.get("medium", 0),
            "crisis_low": crisis.get("low", 0),
            "crisis_total": crisis.get("total", 0),
        })

    # 渲染 + PDF
    html = _render_html(ctx)
    pdf_bytes = _html_to_pdf(html)

    # 缓存
    if use_cache and redis_client:
        try:
            import base64
            redis_client.setex(
                _cache_key(org_id, year_month),
                CACHE_TTL_SECONDS,
                base64.b64encode(pdf_bytes).decode(),
            )
        except Exception as e:
            logging.warning(f"[org_report] cache write fail: {e}")

    return pdf_bytes


def _valid_ym(ym: str) -> bool:
    try:
        y, m = ym.split("-")
        y, m = int(y), int(m)
        return 1900 <= y <= 2100 and 1 <= m <= 12
    except Exception:
        return False


def _ym_to_range(ym: str):
    y, m = map(int, ym.split("-"))
    start = datetime(y, m, 1)
    # 月末:下月 1 号减一秒
    if m == 12:
        end = datetime(y + 1, 1, 1) - timedelta(seconds=1)
    else:
        end = datetime(y, m + 1, 1) - timedelta(seconds=1)
    return start, end


def _labels(locale: str) -> Dict[str, str]:
    if locale == "en":
        return {
            "title": "Team Mental Wellness Report",
            "period": "Period",
            "scope": "Scope",
            "generated": "Generated",
            "n_employees": "Employees in scope",
            "section_engagement": "Engagement",
            "section_sleep": "Sleep",
            "section_anxiety": "Anxiety & Mood",
            "section_worry": "Worry Domains",
            "section_crisis": "Crisis Events",
            "active_users": "Active users",
            "activation": "Activation rate",
            "completion": "Completion rate",
            "sessions": "Total sessions",
            "avg_se": "Average sleep efficiency",
            "avg_tst": "Average sleep time",
            "low_se": "% entries SE < 70%",
            "short_tst": "% entries TST < 6h",
            "users_with_data": "Users with data",
            "se_distribution": "SE distribution",
            "recovery_turns": "Avg calm-down turns",
            "momentum": "Mood-momentum distribution",
            "top_worry": "Top worry domain",
            "total_worry": "Total worry records",
            "high_risk": "High-risk events",
            "medium_risk": "Medium-risk events",
            "low_risk": "Low-risk events",
            "crisis_total": "Total crisis events",
            "crisis_anonymous_note": "Counts only. The system never exposes employee identity, conversation content, or raw event text.",
            "privacy_footer": "This report is aggregated under k≥{kmin} anonymity. Smaller cohorts return 'insufficient data' instead of real numbers. HR never sees individual conversation content.",
            "insufficient_title": "Insufficient data",
            "insufficient_body": "Privacy guardrails require ≥ {kmin} employees in scope to display aggregated metrics. Currently: {n}.",
            "disclaimer": "ZhiMian is an AI bedtime companion, not a medical service. In emergencies, employees are directed to professional resources (988 / Crisis Text Line / local hotlines).",
        }
    return {
        "title": "团队心理健康月度报告",
        "period": "周期",
        "scope": "范围",
        "generated": "生成时间",
        "n_employees": "样本员工数",
        "section_engagement": "参与度",
        "section_sleep": "睡眠",
        "section_anxiety": "焦虑与情绪",
        "section_worry": "担忧域分布",
        "section_crisis": "危机事件",
        "active_users": "活跃员工",
        "activation": "激活率",
        "completion": "会话完成率",
        "sessions": "总会话数",
        "avg_se": "平均睡眠效率",
        "avg_tst": "平均睡眠时长",
        "low_se": "低 SE 占比",
        "short_tst": "短 TST 占比",
        "users_with_data": "有数据员工数",
        "se_distribution": "睡眠效率分布",
        "recovery_turns": "平均焦虑消退轮数",
        "momentum": "情绪走向分布",
        "top_worry": "首要担忧域",
        "total_worry": "担忧记录总数",
        "high_risk": "高风险事件",
        "medium_risk": "中风险事件",
        "low_risk": "低风险事件",
        "crisis_total": "总危机事件数",
        "crisis_anonymous_note": "仅返回计数,系统从不向 HR 暴露员工身份、对话内容或事件原文。",
        "privacy_footer": "本报告所有指标均经过 k≥{kmin} 匿名化聚合。少于 {kmin} 人的分组返回'数据不足',HR 永远看不到个人对话内容。",
        "insufficient_title": "数据不足",
        "insufficient_body": "为保护员工隐私,样本量须 ≥ {kmin} 人才能聚合展示。当前: {n} 人。",
        "disclaimer": "知眠是 AI 助眠陪伴产品,不构成医疗服务。员工触发危机时,系统引导专业医疗资源(全国心理援助热线 400-161-9995 / 988 等)。",
    }
