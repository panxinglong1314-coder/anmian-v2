# 知眠 CBT-I 语料库

基于完整失眠认知行为疗法（CBT-I）协议的结构化语料库，供 AI 动态调用。

## 目录结构

```
corpus/
├── CBT-I_MANUAL.md           # 完整 CBT-I 操作手册（核心协议文档）
├── cognitive_distortions.json  # 15种认知扭曲类型（含定义、示例、苏格拉底提问）
├── emotion_keywords.json     # 情绪关键词库（按焦虑/悲伤/愤怒分类，含担忧领域）
├── breathing_scripts.json    # 呼吸引导脚本库（4-7-8/方形呼吸/腹式呼吸）
├── pmr_scripts.json          # 渐进式肌肉放松（PMR）脚本（完整版+快速版）
├── closure_rituals.json     # 关闭仪式模板（含5种变体+动态生成规则）
├── safe_scripts.json        # 安全协议（危机干预话术+热线资源）
└── sleep_hygiene.json       # 睡眠卫生教育内容（咖啡因/酒精/运动/屏幕/环境）
```

## 核心文件说明

### CBT-I_MANUAL.md
**最核心的协议文档**，定义了：
- 7大模块（评估→担忧处理→认知重构→放松诱导→刺激控制→睡眠限制→关闭仪式）
- 会话状态机（PHASE 转换图）
- AI 风格指南（禁止用语/允许用语/语言节奏）
- CBT-I 技术库

### cognitive_distortions.json
15种认知扭曲类型，每种包含：
- 定义
- 中文示例
- 苏格拉底提问模板（每个扭曲4-6个问题）
- 重构建议
- 检测关键词

### emotion_keywords.json
三层结构：
- **情绪类别**：焦虑/悲伤/愤怒/挫败感（各分轻/中/重三级）
- **担忧领域**：工作/人际/亲密关系/家庭/健康/财务/未来/学业
- **认知扭曲信号**：各类扭曲的特征关键词

### breathing_scripts.json
三种呼吸引导技术，每种包含：
- 物理引导描述
- 心理聚焦指引
- TTS 语速参数
- SSML 停顿标记
- 适用条件选择逻辑

### pmr_scripts.json
完整 PMR 身体扫描：
- 14个身体部位（脚趾→全身）
- 每部位：紧张指令 + 放松指令 + 感受关键词
- 配套引入语和过渡语

### closure_rituals.json
5种关闭仪式变体 + 动态生成规则：
- 标准型/焦虑缓解型/平静增强型/担忧处理后型/反刍中断型
- 睡眠诱导短语（倒数法/身体扫描法/睡眠许可法）

## 使用方式

```python
from backend.cbt_manager import cbt_manager

# 处理用户消息
result = cbt_manager.process_message(
    user_id="wx_xxx",
    session_id="session_20260412",
    user_message="我担心明天的工作汇报...",
    conversation_history=[...]
)

# result 包含:
# - response_type: "text" | "breathing" | "pmr" | "closure" | "safety"
# - content: AI 说的话
# - tts_params: TTS 参数（rate, pitch, volume, pause_ms）
# - state_update: 更新后的会话状态
# - next_phase: 下一阶段
# - should_close: 是否应该结束会话
```

## 设计原则

1. **非固定脚本**：所有内容都是结构化模板，由 LLM 根据上下文动态组合
2. **情绪自适应**：同一技术根据焦虑等级调整 TTS 参数和语言风格
3. **安全第一**：危机干预协议独立于其他模块，优先级最高
4. **可扩展**：新增技术或内容只需添加 JSON/修改现有文件，无需改代码

## 更新日志

- **v2.0** (2026-04-12): 完整 CBT-I 语料库，支持动态 LLM 调用，替代原固定脚本模式
