#!/usr/bin/env python3
"""TVBox Desktop — 内置订阅源配置

收录经过验证的可用接口，包括:
- 多仓格式（包含多个单源的集合）
- 单源格式（直接可用的 TVBox JSON 接口）
- IPTV 直播源（M3U/TXT 格式）

用户可在设置中启用/禁用这些内置源，也可以自行添加。
"""

from core.models import SourceInfo

# ============================================================
#  多仓格式源（Multi-warehouse）
#  返回 {urls: [{url, name}, ...]} 结构
# ============================================================
BUILTIN_MULTI_SOURCES = [
    {
        "name": "🚀 精选多仓",
        "url": "https://raw.githubusercontent.com/liu673cn/box/main/m.json",
        "description": "精选多仓合集，持续维护",
    },
    {
        "name": "🐱 肥猫多仓",
        "url": "http://肥猫.com",
        "description": "肥猫维护的多仓源",
    },
    {
        "name": "🍚 饭太硬多仓",
        "url": "http://www.饭太硬.com/tv/",
        "description": "饭太硬维护的多仓源",
    },
    {
        "name": "📦 dxawi 多仓",
        "url": "https://raw.githubusercontent.com/dxawi/0/main/tv/tv.json",
        "description": "dxawi 维护的多仓合集",
    },
    {
        "name": "📦 ygw 多仓",
        "url": "https://raw.githubusercontent.com/YuanGeworks/YuanGuTVBox/main/box.json",
        "description": "元谷维护的多仓源",
    },
]

# ============================================================
#  单源格式源（Single source）
#  直接包含 sites / lives / parses 的 TVBox JSON
# ============================================================
BUILTIN_SINGLE_SOURCES = [
    {
        "name": "📺 小米影视",
        "url": "https://raw.githubusercontent.com/xiaomi12345/xiaomitv/main/tv/1.json",
        "description": "小米影视维护的单源",
    },
    {
        "name": "📺 OK猫",
        "url": "https://ok321.top/tv/ok.json",
        "description": "OK猫维护的单源",
    },
    {
        "name": "📺 饭太硬单源",
        "url": "https://fantaiying.github.io/rrtv/tv/fta.json",
        "description": "饭太硬维护的单源接口",
    },
]

# ============================================================
#  IPTV 直播源
#  M3U 或 TXT 格式的直播频道列表
# ============================================================
BUILTIN_LIVE_SOURCES = [
    {
        "name": "📡 精选直播 (IPv6)",
        "url": "https://raw.githubusercontent.com/fanmingming/live/main/tv/m3u/ipv6.m3u",
        "description": "范明明维护的 IPv6 直播源",
    },
    {
        "name": "📡 精选直播 (IPv4)",
        "url": "https://raw.githubusercontent.com/fanmingming/live/main/tv/m3u/ipv4.m3u",
        "description": "范明明维护的 IPv4 直播源",
    },
    {
        "name": "📡 iptv-org 中国",
        "url": "https://iptv-org.github.io/iptv/countries/cn.m3u",
        "description": "iptv-org 聚合的中国频道",
    },
    {
        "name": "📡 iptv-org 全球",
        "url": "https://iptv-org.github.io/iptv/index.m3u",
        "description": "iptv-org 聚合的全球频道",
    },
]


def get_all_builtin_sources() -> dict:
    """获取所有内置源，按类别分组返回"""
    return {
        "multi": BUILTIN_MULTI_SOURCES,
        "single": BUILTIN_SINGLE_SOURCES,
        "live": BUILTIN_LIVE_SOURCES,
    }


def get_builtin_source_urls() -> list:
    """获取所有内置源的 URL 列表（用于去重/快速检查）"""
    urls = []
    for group in (BUILTIN_MULTI_SOURCES, BUILTIN_SINGLE_SOURCES, BUILTIN_LIVE_SOURCES):
        for src in group:
            urls.append(src["url"])
    return urls


def get_builtin_warehouse_sources():
    """获取内置多仓源列表（返回 SourceInfo 对象，兼容旧接口）"""
    return [
        SourceInfo(
            name=s["name"],
            url=s["url"],
            source_type="json",
            repo_name=s.get("description", ""),
        )
        for s in BUILTIN_MULTI_SOURCES
    ]


def get_builtin_single_source_list():
    """获取内置单源列表（返回 SourceInfo 对象）"""
    return [
        SourceInfo(
            name=s["name"],
            url=s["url"],
            source_type="json",
            repo_name=s.get("description", ""),
        )
        for s in BUILTIN_SINGLE_SOURCES
    ]


def get_builtin_live_source_list():
    """获取内置直播源列表（返回 SourceInfo 对象）"""
    return [
        SourceInfo(
            name=s["name"],
            url=s["url"],
            source_type="json",
            repo_name=s.get("description", ""),
        )
        for s in BUILTIN_LIVE_SOURCES
    ]
