"""
pytest 全局配置与共享 fixtures
"""
import pytest
import fakeredis
import json
import os
import sys

# 确保 backend 目录在路径中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


@pytest.fixture
def fake_redis():
    """提供一个独立的 fake Redis 实例（每个测试隔离）"""
    r = fakeredis.FakeRedis(decode_responses=True)
    yield r
    r.flushall()


@pytest.fixture
def emotion_corpus_path():
    """ emotion_keywords.json 真实路径 """
    base = os.path.join(os.path.dirname(__file__), '..', '..', 'corpus')
    path = os.path.join(base, 'emotion_keywords.json')
    if os.path.exists(path):
        return path
    # fallback: 若不存在则返回 None，让 EmotionAnalyzer 使用空语料
    return None
