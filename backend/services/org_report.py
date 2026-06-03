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

# httpx 模块级 import,便于测试 monkeypatch (生产环境必装)
try:
    import httpx
except ImportError:  # pragma: no cover - httpx is in requirements
    httpx = None  # type: ignore


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
    overview_with_deltas: Dict[str, Any] = {}
    if not insufficient:
        try:
            metrics["sleep"] = metric_sleep(user_ids, cutoff)
            metrics["anxiety"] = metric_anxiety(user_ids, cutoff)
            metrics["worry"] = metric_worry_domains(user_ids, cutoff)
            metrics["crisis"] = metric_crisis(user_ids, cutoff, org_id)
            metrics["engagement"] = metric_engagement(user_ids, cutoff, org_id)
        except Exception as e:
            logging.warning(f"[org_report] metric compute partial fail: {e}")
        # V2-4: 同时拿一份带 delta 的 overview,喂给 LLM 写 exec summary
        try:
            from services.org_insights import insights_overview
            # period 算成当月天数(年-月->天差); 默认 30d 一致够用
            period_days = max((period_end - period_start).days, 28)
            overview_with_deltas = insights_overview(
                org_id, team_id=team_id, period=f"{period_days}d",
            ) or {}
        except Exception as e:
            logging.warning(f"[org_report] overview-with-deltas fetch failed: {e}")

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
        # V2-4: LLM Executive Summary
        exec_summary_text: Optional[str] = None
        if overview_with_deltas.get("status") == "ok":
            exec_summary_text = generate_executive_summary(
                metrics_with_deltas=overview_with_deltas,
                org_name=org.get("name", ""),
                period_label=_build_period_label(year_month, locale),
                locale=locale,
            )
        ctx["exec_summary"] = exec_summary_text
        ctx["exec_summary_lines"] = [
            ln.strip().lstrip("•").strip()
            for ln in (exec_summary_text or "").splitlines()
            if ln.strip().startswith("•")
        ] if exec_summary_text else []

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
        # V2-4 LLM Executive Summary 标签
        "exec_summary_title": "本月最值得关注的三点",
        "exec_summary_subtitle": "由 AI 综合 6 维度指标自动生成。事实表述,不替代专业判断。",
        "exec_summary_unavailable": "(本月 AI 摘要暂不可用,请直接查看下方各项指标。)",
    }


# =========================================================================
# V2-4: LLM Executive Summary
# =========================================================================
# 设计要点:
# - 同步实现 (httpx sync, 不流式) — generate_monthly_report 本身是 sync
# - 50% 失败率内可接受:LLM 不可用时回退到模板默认文案,PDF 仍能出
# - 提示词强约束「3 条」「事实表述」「不诊断」,避免医疗建议越界
# - 仅基于 deltas / numbers 推理,绝不引用 user_id / 对话内容
# - max_tokens=300, temperature=0.4 (略保守,避免发挥过度)
# - 超时 12s (PDF 生成已是低 QPS 离线场景,可以耐心等)

LLM_SUMMARY_TIMEOUT_S = 12.0


def _build_exec_summary_prompt(metrics_with_deltas: Dict[str, Any],
                                org_name: str, period_label: str,
                                locale: str) -> list:
    """构造 LLM 提示词。messages list (OpenAI 风格)。

    metrics_with_deltas: 已包含 deltas / 顶层 6 维数字的 dict,
      来自 metric_overview 已平铺过的结构。
    """
    # 压成紧凑文本,避免 prompt 太长
    se = metrics_with_deltas.get("avg_se_pct")
    tst = metrics_with_deltas.get("avg_tst_hours")
    low_se = metrics_with_deltas.get("low_se_ratio")
    crisis_total = metrics_with_deltas.get("crisis_total", 0)
    crisis_high = metrics_with_deltas.get("crisis_high", 0)
    activation = metrics_with_deltas.get("activation_rate")
    completion = metrics_with_deltas.get("completion_rate")
    n = metrics_with_deltas.get("n", 0)
    deltas = metrics_with_deltas.get("deltas", {}) or {}

    def _d(field):
        d = deltas.get(field) or {}
        prev = d.get("prev")
        dpct = d.get("delta_pct")
        trend = d.get("trend", "unknown")
        if prev is None:
            return "暂无上期对比" if locale == "zh" else "no prior data"
        sign = "+" if (dpct or 0) > 0 else ""
        return f"上期 {prev}, 本期 {sign}{dpct}% ({trend})" if locale == "zh" \
               else f"prev {prev}, {sign}{dpct}% ({trend})"

    if locale == "en":
        data_block = (
            f"Organization: {org_name}\nPeriod: {period_label}\n"
            f"Cohort size (k-anonymized): {n} employees\n\n"
            f"Sleep efficiency (avg SE %): {se}  — {_d('avg_se_pct')}\n"
            f"Sleep time (avg TST hours): {tst} — {_d('avg_tst_hours')}\n"
            f"Low SE ratio (% entries <70%): {low_se} — {_d('low_se_ratio')}\n"
            f"Crisis events total: {crisis_total} — {_d('crisis_total')}\n"
            f"  └ high-risk: {crisis_high} — {_d('crisis_high')}\n"
            f"Activation rate: {activation}% — {_d('activation_rate')}\n"
            f"Session completion rate: {completion}% — {_d('completion_rate')}\n"
        )
        system = (
            "You are a workforce wellness analyst. You receive aggregated, "
            "k-anonymized team metrics for an HR audience. NEVER infer about "
            "individuals. NEVER give medical advice or diagnosis. Stick to "
            "what the numbers show. Output EXACTLY 3 bullet points, each "
            "≤ 25 words, observational + neutral tone, in the language of "
            "the user request. Use the pattern: <observation>. "
            "<one-sentence implication for HR>. Output PLAIN TEXT, no markdown."
        )
        user = (
            f"Write the 3 most important takeaways for HR this month.\n\n"
            f"DATA:\n{data_block}\n"
            "Rules:\n"
            "1. EXACTLY 3 bullets, start each with '• '.\n"
            "2. Cite the number explicitly.\n"
            "3. Prioritize: high-risk crisis > sleep deterioration > activation drop.\n"
            "4. If a metric improved, you may include 1 positive bullet.\n"
            "5. End each bullet with one short suggestion (NOT medical advice).\n"
        )
    else:
        data_block = (
            f"企业:{org_name}\n周期:{period_label}\n"
            f"样本量(k 匿名化):{n} 名员工\n\n"
            f"平均睡眠效率 SE: {se}%  — {_d('avg_se_pct')}\n"
            f"平均睡眠时长 TST: {tst} 小时 — {_d('avg_tst_hours')}\n"
            f"低 SE 占比 (<70%): {low_se}% — {_d('low_se_ratio')}\n"
            f"危机事件总数: {crisis_total} — {_d('crisis_total')}\n"
            f"  └ 高风险: {crisis_high} — {_d('crisis_high')}\n"
            f"激活率: {activation}% — {_d('activation_rate')}\n"
            f"会话完成率: {completion}% — {_d('completion_rate')}\n"
        )
        system = (
            "你是一名企业心理健康数据分析师,只服务于 HR 受众。"
            "数据均经 k 匿名化,你**绝不可**推断任何个体情况,"
            "**绝不可**给出医疗建议或诊断。仅基于数字描述事实 + 中性观察。"
            "严格输出**正好 3 条**要点,每条 ≤ 35 字。"
            "句式:<事实观察>。<给 HR 的一句行动建议>。"
            "纯文本,无 markdown 符号。"
        )
        user = (
            f"为 HR 写出本月最值得关注的 3 点。\n\n数据:\n{data_block}\n"
            "规则:\n"
            "1. 正好 3 条要点,每条以 '• ' 开头。\n"
            "2. 必须明确引用数字。\n"
            "3. 优先级:高风险危机 > 睡眠恶化 > 激活率下降。\n"
            "4. 若有改善指标,可保留 1 条正面观察。\n"
            "5. 每条末尾给一条简短的 HR 行动建议(非医疗建议)。\n"
        )
    return [{"role": "system", "content": system},
            {"role": "user", "content": user}]


def generate_executive_summary(
    metrics_with_deltas: Dict[str, Any],
    org_name: str,
    period_label: str,
    locale: str = "zh",
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    timeout: float = LLM_SUMMARY_TIMEOUT_S,
) -> Optional[str]:
    """同步调用 LLM 生成 3 条 executive summary。

    Returns:
        非空字符串 (已包含换行的 3 条要点) on success
        None 当 LLM 未配置 / 网络失败 / 输出格式不可用 — 调用方应回退到默认文案。
    """
    # 加载配置:优先参数,其次环境
    try:
        from infra.settings import settings
        api_key = api_key or settings.deepseek_api_key
        base_url = base_url or settings.deepseek_base_url
        model = model or settings.deepseek_model
    except Exception:
        pass

    if not api_key:
        logging.info("[org_report] LLM summary skipped — no API key")
        return None

    if httpx is None:
        logging.warning("[org_report] httpx unavailable; LLM summary skipped")
        return None

    messages = _build_exec_summary_prompt(
        metrics_with_deltas, org_name, period_label, locale,
    )
    url = f"{(base_url or 'https://api.deepseek.com').rstrip('/')}/chat/completions"
    payload = {
        "model": model or "deepseek-chat",
        "messages": messages,
        "temperature": 0.4,
        "max_tokens": 320,
        "stream": False,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        with httpx.Client(timeout=timeout) as c:
            r = c.post(url, json=payload, headers=headers)
            r.raise_for_status()
            data = r.json()
        text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
        text = (text or "").strip()
        # 简单校验:必须含至少 2 条 '• ' 且总长 < 1000
        if text.count("• ") < 2 or len(text) > 1500:
            logging.warning("[org_report] LLM summary format check failed: %r", text[:200])
            return None
        return text
    except Exception as e:
        logging.warning(f"[org_report] LLM summary call failed: {e}")
        return None
