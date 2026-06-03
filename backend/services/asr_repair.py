"""
ASR 中英混读 LLM 纠错。

设计要点:
- **启发式触发**:transcript 同时含中文 + 英文字母才走 LLM,纯中文/纯英文跳过
  (避免日常 ~95% 流量被无谓加 150-250ms 延迟)
- **失败兜底**:LLM 异常/超时/输出畸形,**绝不**抛错,原样返回 raw
- **安全门**:输出长度突变(>1.6x 或 <0.5x)/ 中文字符严重缺失 → 视为
  LLM 跑偏,回退原文
- 不绑 main.py,便于单测 (不必拉起 FastAPI app)

调用方:tencent_asr_stream 返回处 + WS final result + qwen_asr 返回处
"""
from __future__ import annotations

import asyncio
import logging
from typing import AsyncGenerator, Callable, Optional


REPAIR_SYSTEM_PROMPT = (
    "你是 ASR 转写纠错助手,只修复中英混读时的英文听错。\n"
    "常见错误样例:\n"
    "  '滴 line' / 'D Line' → 'deadline'\n"
    "  '卡 P I' / 'K P I' → 'KPI'\n"
    "  '欧 K R' → 'OKR'\n"
    "  '米头深' → 'meditation'\n"
    "  '瑞 view' → 'review'\n"
    "规则:\n"
    "1. 中文部分**绝不**改动语义、增删字、调整语气。\n"
    "2. 仅修正明显错位的英文术语(产品/职场/技术词)。\n"
    "3. 不补全、不解释、不加标点、不翻译。\n"
    "4. 若原文已正确或没有可改的英文,**原样输出**。\n"
    "5. 只输出一行纠错后的句子,不要任何前缀后缀。"
)


def needs_zh_en_repair(text: str) -> bool:
    """同时含中文 + 英文字母 → 候选纠错。"""
    if not text or len(text.strip()) < 4:
        return False
    has_zh = any('一' <= c <= '鿿' for c in text)
    has_en = any(c.isascii() and c.isalpha() for c in text)
    return has_zh and has_en


def _count_zh(s: str) -> int:
    return sum(1 for c in s if '一' <= c <= '鿿')


async def repair_transcript(
    raw: str,
    llm_streamer: Callable[[list], AsyncGenerator[str, None]],
    enabled: bool = True,
    timeout: float = 4.0,
    min_len: int = 4,
) -> str:
    """对 ASR transcript 做中英混读纠错。失败回 raw,不抛错。

    Args:
        raw: ASR 原始 transcript
        llm_streamer: async 生成器,签名 (messages: list) -> AsyncGen[str, None],
                      例如 main.deepseek_chat 偏函数(预绑 stream=True)
        enabled: 总开关 (settings.asr_llm_repair_enabled)
        timeout: 单次纠错最大等待秒
        min_len: 短于此长度不纠错

    Returns:
        修正后 transcript (绝不为空,失败原样返回 raw)
    """
    if not enabled:
        return raw
    if not needs_zh_en_repair(raw):
        return raw
    if len(raw) < min_len:
        return raw

    messages = [
        {"role": "system", "content": REPAIR_SYSTEM_PROMPT},
        {"role": "user", "content": raw},
    ]
    try:
        text = ""
        async def _consume():
            nonlocal text
            async for chunk in llm_streamer(messages):
                text += chunk
        await asyncio.wait_for(_consume(), timeout=timeout)
        fixed = (text or "").strip()
        if not fixed:
            return raw
        # 长度突变 → 跑偏
        if len(fixed) > len(raw) * 1.6 or len(fixed) < len(raw) * 0.5:
            logging.info("[ASR-Repair] length anomaly raw=%d fixed=%d, fall back",
                         len(raw), len(fixed))
            return raw
        # 中文丢失严重 → 跑偏
        zh_raw = _count_zh(raw)
        zh_fixed = _count_zh(fixed)
        if zh_raw > 0 and zh_fixed < zh_raw * 0.7:
            logging.info("[ASR-Repair] zh char loss raw=%d fixed=%d, fall back",
                         zh_raw, zh_fixed)
            return raw
        if fixed != raw:
            logging.info("[ASR-Repair] '%s' → '%s'", raw, fixed)
        return fixed
    except asyncio.TimeoutError:
        logging.info("[ASR-Repair] timeout %.1fs, fall back to raw", timeout)
        return raw
    except Exception as e:
        logging.warning("[ASR-Repair] error: %s, fall back to raw", e)
        return raw
