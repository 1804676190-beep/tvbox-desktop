#!/usr/bin/env python3
"""TVBox Desktop — 仓库管理器

支持的仓库格式:
- JSON 多仓格式: {urls: [{url, name}, ...]}
- JSON storeHouse 格式: {storeHouse: [{sourceName, sourceUrl}, ...]}
- JSON 数组格式: [{name, url}, ...]
- 单源格式: {sites, lives, ...}（直接作为源）
- TXT 格式: 名称,URL（每行一个）

关键改进:
- 支持多仓格式（urls 字段）
- 支持递归解析多仓中的 URL
- 更完善的错误处理
- 源去重
"""

import re
import json
import requests
from typing import List, Optional
from core.models import Repository, SourceInfo


# ============================================================
#  预设仓库
# ============================================================
PRESET_REPOSITORIES = [
    {"name": "饭太硬仓库", "url": "https://fantaiying.github.io/rrtv/tv/fta.json"},
    {"name": "OK猫仓库", "url": "https://ok321.top/tv/ok.json"},
    {"name": "小米影视仓库", "url": "https://raw.githubusercontent.com/xiaomi12345/xiaomitv/main/tv/1.json"},
    {"name": "dxawi 仓库", "url": "https://raw.githubusercontent.com/dxawi/0/main/tv/tv.json"},
    {"name": "精选多仓", "url": "https://raw.githubusercontent.com/liu673cn/box/main/m.json"},
]


# ============================================================
#  核心接口
# ============================================================

def fetch_repository(repo_url: str, timeout: int = 15, recursive: bool = True) -> List[SourceInfo]:
    """
    拉取仓库，解析出多个订阅源
    
    支持的格式:
    - JSON 多仓: {urls: [{url, name}, ...]}
    - JSON storeHouse: {storeHouse: [{sourceName, sourceUrl}, ...]}
    - JSON 数组: [{name, url}, ...]
    - 单源 JSON: {sites, lives, ...}
    - TXT: 名称,URL
    
    Args:
        repo_url: 仓库 URL
        timeout: 请求超时时间（秒）
        recursive: 是否对多仓格式递归解析（True=展开多仓中的每个URL为独立源）
        
    Returns:
        SourceInfo 列表
    """
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        resp = requests.get(repo_url, headers=headers, timeout=timeout, verify=False)
        resp.raise_for_status()
        content = resp.text.strip()
    except requests.exceptions.Timeout:
        print(f"[Repository] 拉取仓库超时: {repo_url}")
        return []
    except requests.exceptions.ConnectionError:
        print(f"[Repository] 连接仓库失败: {repo_url}")
        return []
    except Exception as e:
        print(f"[Repository] 拉取仓库失败: {e}")
        return []

    # 尝试 JSON 解析
    try:
        data = json.loads(content)
        return _parse_json_repo(data, repo_url, recursive)
    except json.JSONDecodeError:
        pass

    # 尝试 XML 解析（单源可能是 XML 格式）
    if content.strip().startswith('<?xml') or '<video' in content[:500]:
        return [SourceInfo(
            name=_extract_name(repo_url),
            url=repo_url,
            source_type='xml',
            repo_name=_extract_name(repo_url),
        )]

    # 尝试 TXT 解析
    return _parse_txt_repo(content, repo_url)


# ============================================================
#  JSON 格式解析
# ============================================================

def _parse_json_repo(data, repo_url: str, recursive: bool = True) -> List[SourceInfo]:
    """
    解析 JSON 格式仓库
    
    支持多种格式，按优先级尝试:
    1. 多仓格式: {urls: [...]}
    2. storeHouse 格式: {storeHouse: [...]}
    3. JSON 数组: [...]
    4. 单源格式: {sites, lives, ...}
    """
    sources = []

    if not isinstance(data, dict):
        # JSON 数组格式
        if isinstance(data, list):
            return _parse_json_array(data, repo_url)
        return sources

    # 格式1: 多仓格式 {urls: [...]}
    if 'urls' in data and isinstance(data['urls'], list):
        return _parse_multi_warehouse(data['urls'], repo_url, recursive)

    # 格式2: storeHouse 格式 {storeHouse: [...]}
    if 'storeHouse' in data and isinstance(data['storeHouse'], list):
        return _parse_store_house(data['storeHouse'], repo_url)

    # 格式3: 单源格式 {sites, lives, ...}
    if 'sites' in data or 'lives' in data:
        sources.append(SourceInfo(
            name=_extract_name(repo_url),
            url=repo_url,
            source_type='json',
            repo_name=_extract_name(repo_url),
        ))
        return sources

    # 格式4: 包含 urls 字典的其他格式
    for key in ('sources', 'list', 'items'):
        if key in data and isinstance(data[key], list):
            return _parse_json_array(data[key], repo_url)

    return sources


def _parse_multi_warehouse(urls: list, repo_url: str, recursive: bool) -> List[SourceInfo]:
    """
    解析多仓格式
    
    多仓格式: {urls: [{url, name}, ...]}
    
    如果 recursive=True，会对每个 URL 递归拉取解析；
    否则只返回多仓本身的信息。
    """
    sources = []
    repo_name = _extract_name(repo_url)

    for item in urls:
        if isinstance(item, dict):
            url = item.get('url', '').strip()
            name = item.get('name', '').strip() or '未命名源'
        elif isinstance(item, str):
            url = item.strip()
            name = '未命名源'
        else:
            continue

        if not url:
            continue

        if recursive:
            # 递归拉取每个子源
            try:
                sub_sources = fetch_repository(url, timeout=15, recursive=False)
                for src in sub_sources:
                    # 保留多仓中的名称（如果子源没有更好的名称）
                    if src.name == _extract_name(url) or not src.name:
                        src.name = name
                    src.repo_name = repo_name
                    sources.append(src)
            except Exception as e:
                print(f"[Repository] 递归解析多仓子源失败 [{name}]: {e}")
                # 失败时仍添加为源，让用户可以手动尝试
                sources.append(SourceInfo(
                    name=name,
                    url=url,
                    source_type='json',
                    repo_name=repo_name,
                ))
        else:
            # 不递归，直接添加
            sources.append(SourceInfo(
                name=name,
                url=url,
                source_type='json',
                repo_name=repo_name,
            ))

    return sources


def _parse_store_house(items: list, repo_url: str) -> List[SourceInfo]:
    """
    解析 storeHouse 格式
    
    格式: {storeHouse: [{sourceName, sourceUrl}, ...]}
    """
    sources = []
    repo_name = _extract_name(repo_url)

    for item in items:
        if not isinstance(item, dict):
            continue

        name = item.get('sourceName', item.get('name', '')).strip() or '未命名源'
        url = item.get('sourceUrl', item.get('url', '')).strip()

        if url:
            sources.append(SourceInfo(
                name=name,
                url=url,
                source_type='json',
                repo_name=repo_name,
            ))

    return sources


def _parse_json_array(items: list, repo_url: str) -> List[SourceInfo]:
    """
    解析 JSON 数组格式
    
    格式: [{name, url}, ...]
    """
    sources = []
    repo_name = _extract_name(repo_url)

    for item in items:
        if not isinstance(item, dict):
            continue

        name = item.get('name', item.get('sourceName', item.get('title', ''))).strip() or '未命名源'
        url = item.get('url', item.get('sourceUrl', item.get('link', ''))).strip()

        if url:
            # 判断 source_type
            source_type = 'json'
            ext = url.split('?')[0].rsplit('.', 1)
            if len(ext) > 1 and ext[-1].lower() in ('xml',):
                source_type = 'xml'

            sources.append(SourceInfo(
                name=name,
                url=url,
                source_type=source_type,
                repo_name=repo_name,
            ))

    return sources


# ============================================================
#  TXT 格式解析
# ============================================================

def _parse_txt_repo(content: str, repo_url: str) -> List[SourceInfo]:
    """
    解析 TXT 格式仓库
    
    支持格式:
    - 名称,URL
    - 名称 URL（空格分隔）
    - 名称\tURL（制表符分隔）
    """
    sources = []
    repo_name = _extract_name(repo_url)

    for line in content.split('\n'):
        line = line.strip()
        if not line or line.startswith('#') or line.startswith('//'):
            continue

        # 尝试多种分隔符
        parts = re.split(r'[,，\t]+', line, maxsplit=1)
        if len(parts) == 2:
            name, url = parts[0].strip(), parts[1].strip()
            if url.startswith('http'):
                sources.append(SourceInfo(
                    name=name or '未命名源',
                    url=url,
                    source_type='json',
                    repo_name=repo_name,
                ))

    return sources


# ============================================================
#  辅助方法
# ============================================================

def _extract_name(url: str) -> str:
    """从 URL 提取仓库名"""
    patterns = [
        (r'github\.com/([^/]+)/([^/]+)', lambda m: f'{m.group(1)}/{m.group(2)}'),
        (r'([^/]+)\.github\.io/([^/]+)', lambda m: f'{m.group(1)}/{m.group(2)}'),
        (r'/tv/([^/?]+)\.json', lambda m: m.group(1)),
        (r'/([^/?]+)\.(?:json|txt|m3u)', lambda m: m.group(1)),
    ]
    for pat, extract in patterns:
        m = re.search(pat, url)
        if m:
            return extract(m)
    m = re.search(r'https?://([^/]+)', url)
    return m.group(1) if m else '未知仓库'


def deduplicate_sources(sources: List[SourceInfo]) -> List[SourceInfo]:
    """
    源去重（基于 URL）
    
    保留第一个出现的源，丢弃后续重复的。
    """
    seen_urls = set()
    unique = []
    for src in sources:
        if src.url not in seen_urls:
            seen_urls.add(src.url)
            unique.append(src)
    return unique


def merge_repositories(repo_sources: List[List[SourceInfo]]) -> List[SourceInfo]:
    """
    合并多个仓库的源列表，自动去重
    
    Args:
        repo_sources: 多个仓库的 SourceInfo 列表
        
    Returns:
        去重后的合并列表
    """
    all_sources = []
    for sources in repo_sources:
        all_sources.extend(sources)
    return deduplicate_sources(all_sources)
