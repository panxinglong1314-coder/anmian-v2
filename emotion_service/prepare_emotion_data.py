#!/usr/bin/env python3
"""
准备情感分类训练数据
从已有语料中提取和生成训练样本

用法:
  python prepare_emotion_data.py --output ./data/emotion_train.json
"""
import json
import argparse
import os
import random
from datetime import datetime

# 基础情绪分类
EMOTIONS = ["anxiety", "sadness", "anger", "frustration", "neutral", "fear", "loneliness", "exhaustion"]

# 基于已有关键词扩展的训练样本（规则生成 + 人工模板）
TRAINING_TEMPLATES = {
    "anxiety": {
        "mild": [
            "有点担心明天的事情", "心里有点不安", "感觉有点紧张", "静不下心来",
            "脑子里一直在想事情", "有点发愁", "担心睡不着", "怕明天起不来",
            "心里七上八下的", "有点烦，不知道怎么办"
        ],
        "moderate": [
            "心跳得好快，停不下来", "胸口闷闷的，很难受", "一直在想，控制不住",
            "翻来覆去，越想越焦虑", "很难受，脑子停不下来", "感觉要崩溃了",
            "紧张得手心出汗", "肩膀一直绷着，放松不了"
        ],
        "severe": [
            "我快喘不过气来了", "全身发抖，控制不住", "感觉要窒息了",
            "彻底崩溃了，什么都做不了", "焦虑到极致，感觉要疯了"
        ]
    },
    "sadness": {
        "mild": [
            "有点难过", "心情不太好", "感觉失落", "开心不起来",
            "有点郁闷", "最近比较丧", "没什么精神"
        ],
        "moderate": [
            "很难过，忍不住想哭", "心里空空的", "感觉很委屈",
            "沮丧极了，什么都提不起兴趣", "痛苦得睡不着", "好难受"
        ],
        "severe": [
            "觉得活着没意思", "看不到任何希望", "一切都失去了意义",
            "绝望到极点", "没有活下去的动力了"
        ]
    },
    "anger": {
        "mild": [
            "有点烦", "不太爽", "有点烦躁", "心里不舒服"
        ],
        "moderate": [
            "很生气", "气死了", "特别恼火", "愤怒到极点",
            "越想越气", "非常不满"
        ],
        "severe": [
            "恨透了", "想砸东西", "要疯了", "气得浑身发抖"
        ]
    },
    "frustration": {
        "mild": [
            "有点挫败", "不太顺", "感觉卡住了", "进展不顺利"
        ],
        "moderate": [
            "很受挫", "有很强的失败感", "感觉无能为力",
            "努力了很久还是没有结果", "很无力"
        ],
        "severe": [
            "彻底失败了", "完全不行", "做什么都没用",
            "觉得自己一无是处", "永远不可能成功"
        ]
    },
    "neutral": {
        "mild": [
            "还好", "一般", "还行", "就这样吧", "没什么特别的",
            "今天挺正常的", "没什么感觉", "说不上来"
        ]
    },
    "fear": {
        "mild": ["有点害怕", "不太敢", "心里有点怕", "担心发生不好的事"],
        "moderate": ["很害怕", "恐惧", "不敢闭上眼睛", "怕黑", "怕一个人"],
        "severe": [" terrified", "极度恐惧", "怕得要死", "恐惧感淹没了一切"]
    },
    "loneliness": {
        "mild": ["有点孤单", "感觉一个人", "没人理解", "挺寂寞的"],
        "moderate": ["很孤独", "没有人关心我", "被抛弃了", "好孤单"],
        "severe": ["彻底孤独", "世界上只有我一个人", "被所有人遗忘"]
    },
    "exhaustion": {
        "mild": ["有点累", "困", "疲倦", "没力气", "精力不够"],
        "moderate": ["累极了", "精疲力尽", "身体被掏空", "一点力气都没有"],
        "severe": ["累到极限", "完全动不了", "身体和心灵都枯竭了"]
    }
}

# 隐含情绪样本（无关键词，需要语义理解）
IMPLIED_SAMPLES = [
    {"text": "心里堵得慌", "emotion": "sadness", "level": "moderate"},
    {"text": "有种说不出的难受", "emotion": "sadness", "level": "moderate"},
    {"text": "胸口像压了块石头", "emotion": "anxiety", "level": "moderate"},
    {"text": "脑子嗡嗡的", "emotion": "anxiety", "level": "moderate"},
    {"text": "什么都不想做，就这样躺着", "emotion": "sadness", "level": "moderate"},
    {"text": "为什么总是我", "emotion": "frustration", "level": "moderate"},
    {"text": "已经尽力了，还是这样", "emotion": "frustration", "level": "moderate"},
    {"text": "感觉自己像个透明人", "emotion": "loneliness", "level": "moderate"},
    {"text": "热闹是他们的，我什么都没有", "emotion": "loneliness", "level": "moderate"},
    {"text": "连哭都没力气了", "emotion": "exhaustion", "level": "severe"},
    {"text": "睁着眼到天亮", "emotion": "anxiety", "level": "moderate"},
    {"text": "翻来覆去就是睡不着", "emotion": "anxiety", "level": "mild"},
    {"text": "不想面对明天", "emotion": "sadness", "level": "moderate"},
    {"text": "活着好辛苦", "emotion": "sadness", "level": "severe"},
    {"text": "如果能一觉不醒就好了", "emotion": "sadness", "level": "severe", "suicide_risk": 0.6},
    {"text": "没人会记得我吧", "emotion": "loneliness", "level": "moderate"},
    {"text": "所有的努力都白费了", "emotion": "frustration", "level": "moderate"},
    {"text": "为什么我做不到别人那样", "emotion": "frustration", "level": "moderate"},
    {"text": "一想到要面对就心慌", "emotion": "anxiety", "level": "moderate"},
    {"text": "呼吸都不顺畅", "emotion": "anxiety", "level": "moderate"},
]


def level_to_intensity(level: str) -> int:
    return {"mild": 2, "moderate": 3, "severe": 5}.get(level, 2)


def generate_training_data() -> list:
    """生成训练数据集"""
    samples = []
    
    # 1. 从模板生成
    for emotion, levels in TRAINING_TEMPLATES.items():
        for level, texts in levels.items():
            for text in texts:
                samples.append({
                    "text": text,
                    "emotion": emotion,
                    "level": level,
                    "intensity": level_to_intensity(level),
                    "source": "template"
                })
    
    # 2. 隐含情绪样本
    for item in IMPLIED_SAMPLES:
        samples.append({
            "text": item["text"],
            "emotion": item["emotion"],
            "level": item["level"],
            "intensity": level_to_intensity(item["level"]),
            "suicide_risk": item.get("suicide_risk", 0.0),
            "source": "implied"
        })
    
    # 3. 从已有语料加载（如果存在）
    corpus_paths = [
        "/home/ubuntu/anmian/corpus/emollm_sleep.json",
        "./corpus/emollm_sleep.json",
    ]
    for cp in corpus_paths:
        if os.path.exists(cp):
            try:
                with open(cp, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # emollm 数据格式: [{"instruction": "...", "input": "...", "output": "..."}]
                for item in data:
                    if isinstance(item, dict) and "instruction" in item:
                        text = item.get("input", "") or item.get("instruction", "")
                        if text and len(text) < 200:
                            # 简单规则标注（基于关键词）
                            emotion = "neutral"
                            level = "mild"
                            if any(kw in text for kw in ["焦虑", "担心", "紧张", "害怕"]):
                                emotion = "anxiety"
                                level = "moderate" if any(kw in text for kw in ["非常", "很", "特别"]) else "mild"
                            elif any(kw in text for kw in ["难过", "伤心", "痛苦", "绝望"]):
                                emotion = "sadness"
                                level = "moderate" if any(kw in text for kw in ["非常", "很", "特别", "彻底"]) else "mild"
                            samples.append({
                                "text": text,
                                "emotion": emotion,
                                "level": level,
                                "intensity": level_to_intensity(level),
                                "source": "emollm_corpus"
                            })
                print(f"从 {cp} 加载了 {len(data)} 条语料")
            except Exception as e:
                print(f"加载 {cp} 失败: {e}")
    
    # 4. 数据增强：轻微改写
    augmented = []
    for s in samples:
        if s["source"] == "template" and random.random() < 0.3:
            # 简单改写：添加语气词
            variants = [
                s["text"] + "...",
                "唉，" + s["text"],
                s["text"] + "，真的",
                "就是" + s["text"],
            ]
            for v in variants[:2]:
                augmented.append({
                    "text": v,
                    "emotion": s["emotion"],
                    "level": s["level"],
                    "intensity": s["intensity"],
                    "source": "augmented"
                })
    samples.extend(augmented)
    
    # 去重
    seen = set()
    unique = []
    for s in samples:
        key = s["text"]
        if key not in seen:
            seen.add(key)
            unique.append(s)
    
    random.shuffle(unique)
    return unique


def split_train_test(data: list, test_ratio: float = 0.15):
    """划分训练集和测试集"""
    random.shuffle(data)
    split_idx = int(len(data) * (1 - test_ratio))
    return data[:split_idx], data[split_idx:]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="./data/emotion_train.json", help="输出路径")
    parser.add_argument("--test-ratio", type=float, default=0.15, help="测试集比例")
    args = parser.parse_args()
    
    print("=" * 50)
    print("准备情感分类训练数据")
    print("=" * 50)
    
    data = generate_training_data()
    print(f"\n总计生成 {len(data)} 条样本")
    
    # 统计
    emotion_counts = {}
    for s in data:
        emotion_counts[s["emotion"]] = emotion_counts.get(s["emotion"], 0) + 1
    print("\n情绪分布:")
    for emo, cnt in sorted(emotion_counts.items(), key=lambda x: -x[1]):
        print(f"  {emo:12s}: {cnt:4d} 条")
    
    # 划分
    train, test = split_train_test(data, args.test_ratio)
    print(f"\n训练集: {len(train)} 条")
    print(f"测试集: {len(test)} 条")
    
    # 保存
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump({"train": train, "test": test, "meta": {
            "created_at": datetime.now().isoformat(),
            "total": len(data),
            "emotions": list(emotion_counts.keys())
        }}, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ 数据已保存到: {args.output}")
    
    # 同时保存为 transformers 需要的格式
    train_path = args.output.replace(".json", "_train.csv")
    test_path = args.output.replace(".json", "_test.csv")
    
    import csv
    for split_name, split_data in [("train", train), ("test", test)]:
        path = train_path if split_name == "train" else test_path
        with open(path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["text", "label"])
            for s in split_data:
                writer.writerow([s["text"], s["emotion"]])
        print(f"✅ {split_name} CSV 已保存到: {path}")


if __name__ == "__main__":
    main()
