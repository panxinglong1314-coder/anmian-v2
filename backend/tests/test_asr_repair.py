"""
services/asr_repair.py 测试 — ASR 中英混读 LLM 纠错。

要点:
- 触发条件:同时含中文 + 英文字母才走 LLM (避免无谓延迟)
- 失败兜底:LLM 异常/超时/输出畸形,**绝不**抛错,原样返回 raw
- 安全门:输出长度突变 / 中文字符严重缺失 → 视为 LLM 跑偏,回退
"""
import asyncio
import pytest


# ============== needs_zh_en_repair 启发式 ==============

def test_needs_repair_pure_zh_skipped():
    from services.asr_repair import needs_zh_en_repair
    assert needs_zh_en_repair("今天压力好大") is False


def test_needs_repair_pure_en_skipped():
    from services.asr_repair import needs_zh_en_repair
    assert needs_zh_en_repair("today was rough at work") is False


def test_needs_repair_short_skipped():
    from services.asr_repair import needs_zh_en_repair
    assert needs_zh_en_repair("ok") is False
    assert needs_zh_en_repair("") is False
    assert needs_zh_en_repair(None) is False


def test_needs_repair_mixed_triggered():
    from services.asr_repair import needs_zh_en_repair
    assert needs_zh_en_repair("今天 deadline 太多了") is True
    assert needs_zh_en_repair("PMR 帮我放松") is True
    assert needs_zh_en_repair("project review 让我头疼") is True


# ============== repair_transcript ==============
# helper: 构造一个 fake 流式生成器

def make_streamer(text: str, raise_after: bool = False):
    """返回一个 async 生成器函数,签名同 deepseek_chat。"""
    async def _stream(messages):
        for ch in text:
            yield ch
        if raise_after:
            raise RuntimeError("post-stream error")
    return _stream


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) \
        if asyncio.get_event_loop().is_running() else asyncio.run(coro)


def test_repair_short_circuits_when_disabled():
    from services.asr_repair import repair_transcript
    out = asyncio.run(repair_transcript(
        "今天 deadline 太多", make_streamer("never_called"),
        enabled=False,
    ))
    assert out == "今天 deadline 太多"


def test_repair_pure_zh_does_not_call_llm():
    """纯中文跳过,LLM 不应被调用。"""
    from services.asr_repair import repair_transcript
    called = {"n": 0}
    async def _streamer(messages):
        called["n"] += 1
        yield "should not be called"
    out = asyncio.run(repair_transcript(
        "今天我心情很糟", _streamer, enabled=True,
    ))
    assert out == "今天我心情很糟"
    assert called["n"] == 0


def test_repair_replaces_misheard_term():
    """LLM 正常返回:替换错位英文。"""
    from services.asr_repair import repair_transcript
    out = asyncio.run(repair_transcript(
        "今天 D line 太多了",
        make_streamer("今天 deadline 太多了"),
        enabled=True,
    ))
    assert out == "今天 deadline 太多了"


def test_repair_rejects_length_anomaly():
    """LLM 输出长度突变 > 1.6x → 视为跑偏,回原文。"""
    from services.asr_repair import repair_transcript
    raw = "今天 dline 多"
    long_fixed = "今天 deadline 太多了,我感觉非常焦虑,睡眠也不好,工作压力大"
    out = asyncio.run(repair_transcript(
        raw, make_streamer(long_fixed), enabled=True,
    ))
    assert out == raw


def test_repair_rejects_chinese_loss():
    """LLM 把中文丢了一半 → 回退。"""
    from services.asr_repair import repair_transcript
    raw = "今天 dline 太多了"
    bad = "deadline 多"   # 中文从 5 字 → 1 字 (远低于 70% 阈值)
    out = asyncio.run(repair_transcript(
        raw, make_streamer(bad), enabled=True,
    ))
    assert out == raw


def test_repair_fallback_on_timeout():
    """LLM 卡死 → 超时 → 回原文。"""
    from services.asr_repair import repair_transcript
    async def _slow(messages):
        await asyncio.sleep(5)
        yield ""
    raw = "今天 deadline 太多了"
    out = asyncio.run(repair_transcript(
        raw, _slow, enabled=True, timeout=0.05,
    ))
    assert out == raw


def test_repair_fallback_on_exception():
    """LLM 抛错 → 回原文,不应外抛。"""
    from services.asr_repair import repair_transcript
    async def _bomb(messages):
        raise RuntimeError("network down")
        yield ""   # pragma: no cover

    raw = "今天 deadline 太多"
    out = asyncio.run(repair_transcript(
        raw, _bomb, enabled=True,
    ))
    assert out == raw


def test_repair_fallback_on_empty_output():
    """LLM 返回空 → 回原文。"""
    from services.asr_repair import repair_transcript
    raw = "今天 deadline 太多"
    out = asyncio.run(repair_transcript(
        raw, make_streamer(""), enabled=True,
    ))
    assert out == raw


def test_repair_keeps_original_when_llm_matches():
    """LLM 返回与原文一致 → 透传(等价于无操作)。"""
    from services.asr_repair import repair_transcript
    raw = "今天 deadline 太多了"
    out = asyncio.run(repair_transcript(
        raw, make_streamer(raw), enabled=True,
    ))
    assert out == raw
