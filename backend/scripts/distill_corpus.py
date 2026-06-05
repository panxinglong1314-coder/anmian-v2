#!/usr/bin/env python3
"""
P1-6 QA 蒸馏脚本 (2026-06) — 从 session_logger 的高质量会话中蒸馏 AI 话术,
产出 /tmp/distilled_corpus.json 供人工审核,通过后追加到 corpus/。

设计:
- **零数据也能跑** — 没有 session 返回 "no data" 直接退出,不会炸
- 调用 LLM (DeepSeek) 对每个"高分 + closure" 的成功对话做蒸馏:
  "这通对话里 AI 用了什么话术让用户觉得被理解 / 改善了睡眠?"
  → 输出 1-3 条可复用的微技术 / 句式
- 结果分组(by scenario × outcome) 写到 JSON
- **不直接写入 corpus** — 用人工 review 一遍才能合入 (避免 hallucinated 内容污染语料)

用法:
  python3 backend/scripts/distill_corpus.py
    [--min-score 6.0] [--limit 50] [--out /tmp/distilled.json] [--dry-run]

依赖:
- backend/session_logger.py 的 get_training_data_for_l3()
- backend/infra/settings.py 的 deepseek_api_key (可选,无则只 dump 候选不调 LLM)
"""
import argparse
import asyncio
import json
import sys
from collections import defaultdict
from pathlib import Path

# 让脚本能从仓库任意位置启动
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


DISTILL_PROMPT_SYS = """你是一名 CBT-I 治疗对话分析师。我会给你一段用户与 AI 助眠陪伴的真实对话, 用户最终睡得不错(高评分 + 完成关闭仪式)。

任务:从 AI 端的话术里提炼 1-3 条可复用的"微技术 / 句式 / 切入角度",输出 JSON 数组。每条含:
- "skill_name": 短名 (中文, ≤ 10 字, 例 "情绪客体化")
- "pattern": 句式骨架, 用 {...} 占位用户变量 (例 "听起来{情绪词}, 不太好受")
- "when_to_use": 触发场景 (1 句话)
- "why_works": 为什么有效 (1 句话, CBT-I 角度)

规则:
1. 只挑 AI 实际用过的, **不要发明新话术**
2. 避开通用客套("嗯", "我懂")
3. 同义重复合并成 1 条
4. 一律输出合法 JSON 数组, 不要 markdown 围栏
"""


def _llm_call_sync(system: str, user: str, timeout: float = 25.0) -> str:
    """同步调 DeepSeek; 失败返 ''。"""
    try:
        from infra.settings import settings
        api_key = settings.deepseek_api_key
        base_url = settings.deepseek_base_url
        model = settings.deepseek_model
    except Exception:
        return ""
    if not api_key:
        return ""
    try:
        import httpx
    except ImportError:
        return ""
    payload = {
        "model": model or "deepseek-chat",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.3,
        "max_tokens": 600,
        "stream": False,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    url = f"{(base_url or 'https://api.deepseek.com').rstrip('/')}/chat/completions"
    try:
        with httpx.Client(timeout=timeout) as c:
            r = c.post(url, json=payload, headers=headers)
            r.raise_for_status()
            d = r.json()
        return (d.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
    except Exception as e:
        print(f"[distill] LLM call failed: {e}")
        return ""


def _format_transcript(messages: list) -> str:
    """把对话渲染成可读文本喂 LLM。"""
    lines = []
    for m in messages:
        role = "用户" if m.get("role") == "user" else "AI"
        content = (m.get("content") or "").strip()
        if not content:
            continue
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-score", type=float, default=6.0,
                    help="筛选高分会话的最低分数 (默认 6.0/10)")
    ap.add_argument("--limit", type=int, default=50,
                    help="最多处理的会话数 (避免 LLM 烧太久)")
    ap.add_argument("--out", default="/tmp/distilled_corpus.json",
                    help="输出 JSON 路径")
    ap.add_argument("--dry-run", action="store_true",
                    help="只 dump 候选, 不调 LLM (用来看有多少数据)")
    args = ap.parse_args()

    print(f"[distill] 加载高质量训练数据 (min_score={args.min_score})...")
    try:
        from session_logger import session_logger
        sessions = session_logger.get_training_data_for_l3(
            min_score=args.min_score, limit=args.limit,
        )
    except Exception as e:
        print(f"[distill] 无法加载 session_logger: {e}")
        sys.exit(1)

    if not sessions:
        print("[distill] 0 条高质量会话 — 等积累更多数据后再跑")
        Path(args.out).write_text(json.dumps({"sessions": 0, "skills_by_scenario": {}}, ensure_ascii=False, indent=2))
        return

    print(f"[distill] {len(sessions)} 条会话待蒸馏")

    if args.dry_run:
        # 只 dump 原始
        summary = defaultdict(int)
        for s in sessions:
            summary[s.get("scenario", "unknown")] += 1
        print("[distill] dry-run summary by scenario:")
        for k, v in summary.items():
            print(f"  {k}: {v}")
        Path(args.out).write_text(json.dumps({
            "sessions": len(sessions),
            "by_scenario": dict(summary),
        }, ensure_ascii=False, indent=2))
        return

    # 真蒸馏:对每条会话独立 call LLM
    skills_by_scenario = defaultdict(list)
    success_count = 0
    failed = 0
    for i, sess in enumerate(sessions):
        scenario = sess.get("scenario", "unknown")
        messages = sess.get("messages", [])
        if len(messages) < 4:
            continue
        transcript = _format_transcript(messages)
        if not transcript:
            continue
        print(f"[distill] [{i+1}/{len(sessions)}] scenario={scenario} effect={sess.get('effectiveness_score')}")
        raw = _llm_call_sync(DISTILL_PROMPT_SYS, transcript[:4000])
        if not raw:
            failed += 1
            continue
        # 尝试解析 LLM 输出为 JSON 数组
        try:
            arr = json.loads(raw)
            if isinstance(arr, list):
                for item in arr:
                    if isinstance(item, dict) and "skill_name" in item:
                        item["_source_session"] = sess.get("session_id", "")
                        skills_by_scenario[scenario].append(item)
                success_count += 1
        except json.JSONDecodeError:
            failed += 1
            continue

    out = {
        "sessions_processed": len(sessions),
        "sessions_with_skills": success_count,
        "sessions_failed": failed,
        "skills_by_scenario": dict(skills_by_scenario),
        "_note": "本文件由 distill_corpus.py 生成,需人工 review 后再合入 corpus/",
    }
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"[distill] ✓ {success_count}/{len(sessions)} 蒸馏成功, {failed} 失败")
    print(f"[distill] 输出: {args.out}")
    print(f"[distill] 下一步:人工 review → 通过的合入 corpus/ → git commit")


if __name__ == "__main__":
    asyncio.run(asyncio.sleep(0))  # 占位避免无 import 警告
    main()
