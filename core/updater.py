#!/usr/bin/env python3
"""TVBox Desktop — 在线更新检查"""

import requests
from typing import Optional
from dataclasses import dataclass

# GitHub 仓库信息
GITHUB_OWNER = "1804676190-beep"
GITHUB_REPO = "tvbox-desktop"
CURRENT_VERSION = "1.2.0"

GITHUB_API = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
GITHUB_RELEASES = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases"


@dataclass
class UpdateInfo:
    """更新信息"""
    version: str
    html_url: str
    body: str
    published_at: str
    download_url: str = ""
    file_size: int = 0
    has_update: bool = False


def check_update(timeout: int = 10) -> Optional[UpdateInfo]:
    """
    检查是否有新版本
    返回 UpdateInfo，如果有更新则 has_update=True
    """
    try:
        headers = {
            'User-Agent': 'TVBox-Desktop',
            'Accept': 'application/vnd.github.v3+json'
        }
        resp = requests.get(GITHUB_API, headers=headers, timeout=timeout, verify=False)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[Updater] 检查更新失败: {e}")
        return None

    tag = data.get('tag_name', '').lstrip('v')
    html_url = data.get('html_url', GITHUB_RELEASES)
    body = data.get('body', '')
    published_at = data.get('published_at', '')

    # 查找 win64 zip 下载链接
    download_url = ""
    file_size = 0
    for asset in data.get('assets', []):
        name = asset.get('name', '').lower()
        if 'win64' in name and name.endswith('.zip'):
            download_url = asset.get('browser_download_url', '')
            file_size = asset.get('size', 0)
            break

    # 版本比较
    has_update = _compare_versions(CURRENT_VERSION, tag)

    return UpdateInfo(
        version=tag,
        html_url=html_url,
        body=body[:500],
        published_at=published_at,
        download_url=download_url,
        file_size=file_size,
        has_update=has_update
    )


def _compare_versions(current: str, latest: str) -> bool:
    """比较版本号，latest > current 返回 True"""
    try:
        def parse(v):
            return [int(x) for x in v.split('.')]
        c = parse(current)
        l = parse(latest)
        max_len = max(len(c), len(l))
        c += [0] * (max_len - len(c))
        l += [0] * (max_len - len(l))
        return l > c
    except Exception:
        return current != latest


def format_size(size_bytes: int) -> str:
    """格式化文件大小"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
