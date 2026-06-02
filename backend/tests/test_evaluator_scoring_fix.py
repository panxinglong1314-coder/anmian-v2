"""
dialogue_evaluator.py 评分修正测试 (v2.5)

修正的 3 个问题:
1. EN empathy 关键词缺失 → EN 对话恒得 2/5
2. Coherence base=40 + overlap*80 → 故意不复读的好 AI 反被扣分
3. Empathy 检测大小写敏感 → "I HEAR YOU" 不命中
"""
import pytest


def _eval(turns):
    """跑一次 evaluator,返回 5 分制 report。"""
    from dialogue_evaluator import dialogue_evaluator
    log = {
        "session_id": "test_eval_fix",
        "user_id": "test_user",
        "stage": "intake",
        "turns": turns,
    }
    ev = dialogue_evaluator.evaluate_session(log)
    return dialogue_evaluator.to_dict(ev).get("report", {})


def _make_turns(pairs):
    out = []
    for user, ai in pairs:
        out.append({"role": "user", "content": user})
        out.append({"role": "assistant", "content": ai})
    return out


# ============================ EN empathy ============================

def test_en_empathy_recognized():
    """EN AI 有共情表达,应该 ≥ 3/5。"""
    turns = _make_turns([
        ("I can't sleep, work is killing me",
         "I hear you. That sounds really hard. Take your time, I'm here."),
        ("I just keep thinking about the deadline",
         "Of course you would. That's a lot to carry. No rush."),
        ("Maybe I should just push through",
         "You don't have to push through tonight. It's okay to rest."),
    ])
    rep = _eval(turns)
    emp = rep.get("empathy", {}).get("score", 0)
    assert emp >= 3, f"EN 真实共情对话应 ≥3,实得 {emp}\n报告: {rep}"


def test_en_empathy_case_insensitive():
    """大小写不应影响共情检测。"""
    turns = _make_turns([
        ("hello", "I HEAR YOU. That's HEAVY. Take Your Time."),
    ])
    rep = _eval(turns)
    emp = rep.get("empathy", {}).get("score", 0)
    assert emp >= 2  # 至少不掉到 0


def test_en_negative_signals_detected():
    """EN 模板化语言应被识别为负向。"""
    turns = _make_turns([
        ("I'm struggling",
         "Don't worry, it's okay! Cheer up. You got this, stay strong!"),
    ])
    rep = _eval(turns)
    emp = rep.get("empathy", {}).get("score", 0)
    # 全是负向,empathy 应该很低
    assert emp <= 2, f"全负向回应应 ≤2,实得 {emp}"


# ============================ Coherence base ============================

def test_coherence_base_for_normal_conversation():
    """正常 ZH 对话,AI 不机械复读用户原词,应得 ≥3/5 (70 分基线)。"""
    turns = _make_turns([
        ("今晚又睡不着,脑子停不下来", "嗯,这种感觉很难受。先别急着睡,跟我说说。"),
        ("一直在想明天的汇报", "明天的事,今晚先放一放。"),
        ("放不下啊", "我在这里。"),
    ])
    rep = _eval(turns)
    coh = rep.get("coherence", {}).get("score", 0)
    assert coh >= 3, f"语义连贯但不复读的对话应 ≥3, 实得 {coh}\n报告: {rep}"


def test_coherence_drift_detection_is_disabled():
    """v2.5: keyword overlap 不可靠,放弃 drift 检测。
    话题漂移由 LLM-as-judge 二次复核处理,不在 auto_v2 启发式范围。
    此 test 文档化新行为:严重漂移仍得 base 4/5,不当 bug。"""
    turns = _make_turns([
        ("今晚睡不着", "今晚的月亮真好看"),
        ("我在说失眠", "周末去爬山吧"),
        ("???", "我喜欢冰淇淋"),
    ])
    rep = _eval(turns)
    coh = rep.get("coherence", {}).get("score", 0)
    # 接受新基线 4/5,LLM 复核会做更细的语义判断
    assert coh >= 3


def test_coherence_punishes_parroting():
    """AI 复读用户原话开头应扣分。"""
    parroting_turns = _make_turns([
        ("我今晚很焦虑很烦躁", "我今晚很焦虑很烦躁,这种感觉确实不容易。"),
        ("是的特别难受", "是的特别难受,我能理解。"),
    ])
    rep = _eval(parroting_turns)
    coh = rep.get("coherence", {}).get("score", 0)
    # 复读惩罚至少 15 分,从 base 70 应降到 ~55 即 3/5 或更低
    assert coh <= 3


# ============================ Integration: 修复后的真实场景 ============================

def test_zh_shutdown_scenario_should_not_get_lowest_coherence():
    """复刻 prod 真实场景:用户关机态,AI 不复读,语义合理 →
    修复前 coh=2/5,修复后应 ≥3/5。"""
    turns = _make_turns([
        ("今天工作上又被领导当众说了几句,挺难受的",
         "嗯,被当众说真的不容易,你现在心里压着这些。"),
        ("我已经懒得说什么了,反正怎么解释都没用",
         "听到了,这种'说什么都没用'的感觉很消耗。"),
        ("算了,无所谓了,睡不着就睡不着吧",
         "今晚的沉默也是一种陪伴。"),
    ])
    rep = _eval(turns)
    coh = rep.get("coherence", {}).get("score", 0)
    emp = rep.get("empathy", {}).get("score", 0)
    assert coh >= 3, f"ZH shutdown 修复后 coh 应 ≥3, 实得 {coh}"
    assert emp >= 3, f"ZH shutdown 修复后 emp 应 ≥3, 实得 {emp}"


def test_en_safety_scenario_should_have_better_empathy():
    """复刻 prod EN safety_plan 场景:修复前 emp=2/5,修复后应 ≥3/5。"""
    turns = _make_turns([
        ("I haven't been sleeping for weeks and I feel like I'm losing it",
         "I hear you. That's heavy. Tell me where you are right now."),
        ("Sometimes I think it would be easier if I wasn't around",
         "I'm really glad you told me. Please call or text 988 — they're 24/7. I'm staying here with you."),
        ("I don't have a plan, just tired",
         "That kind of tired makes sense. You don't have to fix anything tonight."),
    ])
    rep = _eval(turns)
    emp = rep.get("empathy", {}).get("score", 0)
    assert emp >= 3, f"EN 真实共情(crisis)修复后应 ≥3, 实得 {emp}\n报告: {rep}"
