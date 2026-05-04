#!/usr/bin/env python3
"""TVBox Desktop — 仓库管理器"""

import re
import json
import requests
from typing import List
from core.models import Repository, SourceInfo


# 预设仓库
PRESET_REPOSITORIES = [
    {"name": "饭太硬仓库", "url": "https://fantaiying.github.io/rrtv/tv/fta.json"},
    {"name": "OK猫仓库", "url": "https://ok321.top/tv/ok.json"},
    {"name": "小米影视仓库", "url": "https://raw.githubusercontent.com/xiaomi12345/xiaomitv/main/tv/1.json"},
]


def fetch_repository(repo_url: str, timeout: int = 15) -> List[SourceInfo]:
    """
    拉取仓库，解析出多个订阅源
    支持 JSON（storeHouse/数组）和 TXT（名称,URL）格式
    """
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        resp = requests.get(repo_url, headers=headers, timeout=timeout, verify=False)
        resp.raise_for_status()
        content = resp.text.strip()
    except Exception as e:
        print(f"[Repository] 拉取仓库失败: {e}")
        return []

    # 尝试 JSON 解析
    try:
        data = json.loads(content)
        return _parse_json_repo(data, repo_url)
    except json.JSONDecodeError:
        pass

    # 尝试 TXT 解析
    return _parse_txt_repo(content, repo_url)


def _parse_json_repo(data, repo_url: str) -> List[SourceInfo]:
    """解析 JSON 格式仓库"""
    sources = []

    # 格式1: {"storeHouse": [...]}
    if isinstance(data, dict) and 'storeHouse' in data:
        for item in data['storeHouse']:
            src = SourceInfo(
                name=item.get('sourceName', item.get('name', '未命名')),
                url=item.get('sourceUrl', item.get('url', '')),
                source_type='json',
                repo_name=_extract_name(repo_url)
            )
            if src.url:
                sources.append(src)
        return sources

    # 格式2: JSON 数组
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                src = SourceInfo(
                    name=item.get('name', item.get('sourceName', '未命名')),
                    url=item.get('url', item.get('sourceUrl', '')),
                    source_type='json',
                    repo_name=_extract_name(repo_url)
                )
                if src.url:
                    sources.append(src)
        return sources

    # 格式3: 单个 TVBox JSON 源（含 sites/lives）
    if isinstance(data, dict) and ('sites' in data or 'lives' in data):
        src = SourceInfo(
            name=_extract_name(repo_url),
            url=repo_url,
            source_type='json',
            repo_name=_extract_name(repo_url)
        )
        sources.append(src)

    return sources


def _parse_txt_repo(content: str, repo_url: str) -> List[SourceInfo]:
    """解析 TXT 格式仓库"""
    sources = []
    for line in content.split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        # 格式: 名称,URL
        parts = re.split(r'[,，\s]+', line, maxsplit=1)
        if len(parts) == 2:
            name, url = parts
            if url.startswith('http'):
                sources.append(SourceInfo(
                    name=name.strip(),
                    url=url.strip(),
                    source_type='json',
                    repo_name=_extract_name(repo_url)
                ))
    return sources


def _extract_name(url: str) -> str:
    """从 URL 提取仓库名"""
    patterns = [
        (r'github\.com/([^/]+)/([^/]+)', lambda m: f'{m.group(1)}/{m.group(2)}'),
        (r'([^/]+)\.github\.io/([^/]+)', lambda m: f'{m.group(1)}/{m.group(2)}'),
        (r'/tv/([^/?]+)\.json', lambda m: m.group(1)),
        (r'/([^/?]+)\.(?:json|txt)', lambda m: m.group(1)),
    ]
    for pat, extract in patterns:
        m = re.search(pat, url)
        if m:
            return extract(m)
    m = re.search(r'https?://([^/]+)', url)
    return m.group(1) if m else '未知仓库'
