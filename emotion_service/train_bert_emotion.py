#!/usr/bin/env python3
"""
BERT 情感分类微调脚本
使用 transformers + PyTorch 训练轻量中文情感分类模型

硬件要求:
  - 训练: 建议 8GB+ GPU 或 CPU（慢但可行）
  - 推理: 2GB RAM 即可

用法:
  # 1. 先准备数据
  python prepare_emotion_data.py --output ./data/emotion_train.json
  
  # 2. 训练（CPU）
  python train_bert_emotion.py --data ./data/emotion_train.json --epochs 5 --batch-size 16
  
  # 3. 训练（GPU，如果有）
  python train_bert_emotion.py --data ./data/emotion_train.json --epochs 10 --batch-size 32 --device cuda
  
  # 4. 推理测试
  python train_bert_emotion.py --mode infer --model ./models/bert-emotion-best --text "我很难过"
"""
import os
import json
import argparse
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
from transformers import (
    BertTokenizer, BertForSequenceClassification,
    AutoTokenizer, AutoModelForSequenceClassification,
    get_linear_schedule_with_warmup
)
from torch.optim import AdamW
from sklearn.metrics import accuracy_score, classification_report, f1_score
from tqdm import tqdm
import numpy as np

# 情绪标签映射
EMOTION_LABELS = ["anxiety", "sadness", "anger", "frustration", "neutral", "fear", "loneliness", "exhaustion"]
LABEL2ID = {label: i for i, label in enumerate(EMOTION_LABELS)}
ID2LABEL = {i: label for label, i in LABEL2ID.items()}


class EmotionDataset(Dataset):
    def __init__(self, data, tokenizer, max_len=128):
        self.data = data
        self.tokenizer = tokenizer
        self.max_len = max_len
    
    def __len__(self):
        return len(self.data)
    
    def __getitem__(self, idx):
        item = self.data[idx]
        text = item["text"]
        label = LABEL2ID.get(item["emotion"], LABEL2ID["neutral"])
        
        encoding = self.tokenizer(
            text,
            max_length=self.max_len,
            padding="max_length",
            truncation=True,
            return_tensors="pt"
        )
        
        return {
            "input_ids": encoding["input_ids"].squeeze(0),
            "attention_mask": encoding["attention_mask"].squeeze(0),
            "label": torch.tensor(label, dtype=torch.long)
        }


def train_epoch(model, dataloader, optimizer, scheduler, device):
    model.train()
    total_loss = 0
    for batch in tqdm(dataloader, desc="Training"):
        input_ids = batch["input_ids"].to(device)
        attention_mask = batch["attention_mask"].to(device)
        labels = batch["label"].to(device)
        
        optimizer.zero_grad()
        outputs = model(input_ids=input_ids, attention_mask=attention_mask, labels=labels)
        loss = outputs.loss
        loss.backward()
        
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
        scheduler.step()
        
        total_loss += loss.item()
    
    return total_loss / len(dataloader)


def eval_model(model, dataloader, device):
    model.eval()
    preds, true_labels = [], []
    total_loss = 0
    
    with torch.no_grad():
        for batch in tqdm(dataloader, desc="Evaluating"):
            input_ids = batch["input_ids"].to(device)
            attention_mask = batch["attention_mask"].to(device)
            labels = batch["label"].to(device)
            
            outputs = model(input_ids=input_ids, attention_mask=attention_mask, labels=labels)
            total_loss += outputs.loss.item()
            
            logits = outputs.logits
            preds.extend(torch.argmax(logits, dim=1).cpu().numpy())
            true_labels.extend(labels.cpu().numpy())
    
    acc = accuracy_score(true_labels, preds)
    f1 = f1_score(true_labels, preds, average="weighted")
    report = classification_report(true_labels, preds, target_names=EMOTION_LABELS, zero_division=0)
    
    return total_loss / len(dataloader), acc, f1, report


def train(args):
    print("=" * 60)
    print("BERT 情感分类微调")
    print("=" * 60)
    
    # 加载数据
    with open(args.data, "r", encoding="utf-8") as f:
        dataset = json.load(f)
    train_data = dataset["train"]
    test_data = dataset["test"]
    
    print(f"\n训练集: {len(train_data)} 条")
    print(f"测试集: {len(test_data)} 条")
    print(f"情绪类别: {EMOTION_LABELS}")
    
    # 设备
    device = torch.device(args.device if torch.cuda.is_available() and args.device == "cuda" else "cpu")
    print(f"设备: {device}")
    
    # 加载模型和 tokenizer
    print(f"\n加载预训练模型: {args.model_name}")
    tokenizer = AutoTokenizer.from_pretrained(args.model_name)
    model = AutoModelForSequenceClassification.from_pretrained(
        args.model_name,
        num_labels=len(EMOTION_LABELS),
        id2label=ID2LABEL,
        label2id=LABEL2ID
    )
    model = model.to(device)
    
    # 数据集
    train_dataset = EmotionDataset(train_data, tokenizer, max_len=args.max_len)
    test_dataset = EmotionDataset(test_data, tokenizer, max_len=args.max_len)
    
    train_loader = DataLoader(train_dataset, batch_size=args.batch_size, shuffle=True)
    test_loader = DataLoader(test_dataset, batch_size=args.batch_size)
    
    # 优化器
    optimizer = AdamW(model.parameters(), lr=args.lr, weight_decay=0.01)
    total_steps = len(train_loader) * args.epochs
    scheduler = get_linear_schedule_with_warmup(
        optimizer,
        num_warmup_steps=int(total_steps * 0.1),
        num_training_steps=total_steps
    )
    
    # 训练循环
    best_f1 = 0
    os.makedirs(args.output_dir, exist_ok=True)
    
    for epoch in range(args.epochs):
        print(f"\n--- Epoch {epoch + 1}/{args.epochs} ---")
        train_loss = train_epoch(model, train_loader, optimizer, scheduler, device)
        eval_loss, acc, f1, report = eval_model(model, test_loader, device)
        
        print(f"Train Loss: {train_loss:.4f}")
        print(f"Eval Loss:  {eval_loss:.4f}")
        print(f"Accuracy:   {acc:.4f}")
        print(f"F1 Score:   {f1:.4f}")
        print(f"\nClassification Report:\n{report}")
        
        # 保存最佳模型
        if f1 > best_f1:
            best_f1 = f1
            best_path = os.path.join(args.output_dir, "bert-emotion-best")
            model.save_pretrained(best_path)
            tokenizer.save_pretrained(best_path)
            print(f"✅ 最佳模型已保存 (F1={f1:.4f}): {best_path}")
    
    # 保存最终模型
    final_path = os.path.join(args.output_dir, "bert-emotion-final")
    model.save_pretrained(final_path)
    tokenizer.save_pretrained(final_path)
    print(f"\n✅ 最终模型已保存: {final_path}")
    print(f"🎯 最佳 F1: {best_f1:.4f}")
    
    # 保存标签映射
    with open(os.path.join(args.output_dir, "label_map.json"), "w", encoding="utf-8") as f:
        json.dump({"id2label": ID2LABEL, "label2id": LABEL2ID}, f, ensure_ascii=False, indent=2)


def infer(args):
    device = torch.device(args.device if torch.cuda.is_available() and args.device == "cuda" else "cpu")
    
    print(f"加载模型: {args.model}")
    tokenizer = AutoTokenizer.from_pretrained(args.model)
    model = AutoModelForSequenceClassification.from_pretrained(args.model)
    model = model.to(device)
    model.eval()
    
    texts = [args.text] if args.text else []
    if args.text_file and os.path.exists(args.text_file):
        with open(args.text_file, "r", encoding="utf-8") as f:
            texts.extend([line.strip() for line in f if line.strip()])
    
    for text in texts:
        encoding = tokenizer(text, max_length=128, padding="max_length", truncation=True, return_tensors="pt")
        input_ids = encoding["input_ids"].to(device)
        attention_mask = encoding["attention_mask"].to(device)
        
        with torch.no_grad():
            outputs = model(input_ids=input_ids, attention_mask=attention_mask)
            probs = torch.softmax(outputs.logits, dim=1)[0]
        
        pred_id = torch.argmax(probs).item()
        pred_label = ID2LABEL[pred_id]
        confidence = probs[pred_id].item()
        
        #  Top-3
        top3 = torch.topk(probs, k=min(3, len(EMOTION_LABELS)))
        top3_labels = [(ID2LABEL[i.item()], p.item()) for i, p in zip(top3.indices, top3.values)]
        
        print(f"\n文本: {text}")
        print(f"预测: {pred_label} (置信度: {confidence:.2%})")
        print("Top-3:")
        for label, prob in top3_labels:
            print(f"  {label}: {prob:.2%}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["train", "infer"], default="train")
    parser.add_argument("--data", default="./data/emotion_train.json")
    parser.add_argument("--model_name", default="bert-base-chinese", help="预训练模型名称")
    parser.add_argument("--model", default="./models/bert-emotion-best", help="推理时加载的模型路径")
    parser.add_argument("--output_dir", default="./models")
    parser.add_argument("--epochs", type=int, default=5)
    parser.add_argument("--batch_size", type=int, default=16)
    parser.add_argument("--lr", type=float, default=2e-5)
    parser.add_argument("--max_len", type=int, default=128)
    parser.add_argument("--device", default="cpu", choices=["cpu", "cuda"])
    parser.add_argument("--text", default=None, help="推理文本")
    parser.add_argument("--text_file", default=None, help="推理文本文件")
    args = parser.parse_args()
    
    if args.mode == "train":
        train(args)
    else:
        infer(args)


if __name__ == "__main__":
    main()
