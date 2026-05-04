#!/usr/bin/env python3
"""TVBox Desktop — 订阅源解析器"""

import re
import json
import requests
from typing import Optional
from bs4 import BeautifulSoup
from core.models import VideoItem, LiveChannel, Category, SourceInfo


class SourceManager:
    """订阅源管理器 — 拉取、解析、搜索"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        self.session.verify = False

    def fetch_source(self, source: SourceInfo) -> dict:
        """
        拉取并解析订阅源
        返回: {'categories': [Category], 'live_channels': [LiveChannel]}
        """
        try:
            resp = self.session.get(source.url, timeout=15)
            resp.raise_for_status()
            content = resp.text.strip()
        except Exception as e:
            print(f"[SourceManager] 拉取源失败 [{source.name}]: {e}")
            return {'categories': [], 'live_channels': []}

        if source.source_type == 'xml' or content.startswith('<?xml') or '<video' in content[:500]:
            return self._parse_xml_source(content)
        else:
            return self._parse_json_source(content, source.url)

    def _parse_json_source(self, content: str, base_url: str) -> dict:
        """解析 TVBox JSON 格式源"""
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            return {'categories': [], 'live_channels': []}

        categories = []
        live_channels = []

        # 解析分类 (sites)
        sites = data.get('sites', [])
        api_url = ''
        for site in sites:
            if site.get('type') in (1, 0, 4):
                api_url = site.get('api', '')
                break

        if not api_url and sites:
            api_url = sites[0].get('api', '')

        # 如果有 API 地址，拉取分类列表
        if api_url:
            categories = self._fetch_categories(api_url)

        # 解析直播源 (lives)
        for live in data.get('lives', []):
            live_url = live.get('url', '')
            live_name = live.get('name', '直播')
            if live_url:
                channels = self._fetch_live_channels(live_url)
                live_channels.extend(channels)

        return {'categories': categories, 'live_channels': live_channels}

    def _fetch_categories(self, api_url: str) -> list:
        """通过 API 拉取分类列表"""
        categories = []
        try:
            url = api_url.rstrip('/') + '?ac=list'
            resp = self.session.get(url, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            for cls in data.get('class', []):
                type_id = cls.get('type_id', '')
                type_name = cls.get('type_name', '')
                if type_id:
                    cat = Category(name=type_name, type_id=str(type_id))
                    # 拉取分类下的视频列表
                    cat.items = self._fetch_category_items(api_url, str(type_id))
                    categories.append(cat)
        except Exception as e:
            print(f"[SourceManager] 拉取分类失败: {e}")
        return categories

    def _fetch_category_items(self, api_url: str, type_id: str, page: int = 1) -> list:
        """拉取分类下的视频列表"""
        items = []
        try:
            url = api_url.rstrip('/') + f'?ac=list&t={type_id}&pg={page}'
            resp = self.session.get(url, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            for vod in data.get('list', []):
                item = VideoItem(
                    name=vod.get('vod_name', ''),
                    url=vod.get('vod_id', ''),
                    pic=vod.get('vod_pic', ''),
                    group=vod.get('type_name', ''),
                    year=vod.get('vod_year', ''),
                    area=vod.get('vod_area', ''),
                    director=vod.get('vod_director', ''),
                    actor=vod.get('vod_actor', ''),
                )
                if item.name:
                    items.append(item)
        except Exception as e:
            print(f"[SourceManager] 拉取分类内容失败: {e}")
        return items

    def fetch_detail(self, api_url: str, vod_id: str) -> Optional[VideoItem]:
        """获取视频详情（含多线路播放地址）"""
        try:
            url = api_url.rstrip('/') + f'?ac=detail&ids={vod_id}'
            resp = self.session.get(url, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            vod_list = data.get('list', [])
            if not vod_list:
                return None

            vod = vod_list[0]
            video = VideoItem(
                name=vod.get('vod_name', ''),
                url=str(vod.get('vod_id', '')),
                pic=vod.get('vod_pic', ''),
                group=vod.get('type_name', ''),
                description=vod.get('vod_content', ''),
                year=vod.get('vod_year', ''),
                area=vod.get('vod_area', ''),
                type_name=vod.get('type_name', ''),
                director=vod.get('vod_director', ''),
                actor=vod.get('vod_actor', ''),
            )

            # 解析多线路
            play_from = vod.get('vod_play_from', '')
            play_url = vod.get('vod_play_url', '')

            if play_from and play_url:
                sources_names = play_from.split('$$$')
                sources_urls = play_url.split('$$$')

                for i, src_name in enumerate(sources_names):
                    src_name = src_name.strip()
                    if i < len(sources_urls):
                        episodes = self._parse_episodes(sources_urls[i])
                        if episodes:
                            video.play_sources.append({
                                'name': src_name,
                                'episodes': episodes
                            })

                # 默认显示第一条线路的剧集
                if video.play_sources:
                    video.episodes = video.play_sources[0]['episodes']

            return video
        except Exception as e:
            print(f"[SourceManager] 获取详情失败: {e}")
            return None

    def _parse_episodes(self, play_url: str) -> list:
        """解析剧集列表"""
        episodes = []
        # 格式: 集名$url#集名$url#...
        parts = play_url.split('#')
        for part in parts:
            if '$' in part:
                ep_name, ep_url = part.split('$', 1)
                ep_name = ep_name.strip()
                ep_url = ep_url.strip()
                if ep_url and ep_name:
                    episodes.append({'name': ep_name, 'url': ep_url})
        return episodes

    def search(self, api_url: str, keyword: str) -> list:
        """搜索影视"""
        items = []
        try:
            url = api_url.rstrip('/') + f'?ac=list&wd={keyword}'
            resp = self.session.get(url, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            for vod in data.get('list', []):
                item = VideoItem(
                    name=vod.get('vod_name', ''),
                    url=str(vod.get('vod_id', '')),
                    pic=vod.get('vod_pic', ''),
                    group=vod.get('type_name', ''),
                    year=vod.get('vod_year', ''),
                )
                if item.name:
                    items.append(item)
        except Exception as e:
            print(f"[SourceManager] 搜索失败: {e}")
        return items

    def _fetch_live_channels(self, live_url: str) -> list:
        """拉取并解析直播源"""
        channels = []
        try:
            resp = self.session.get(live_url, timeout=15)
            resp.raise_for_status()
            content = resp.text.strip()

            if '#EXTINF' in content or '#EXTM3U' in content:
                channels = self._parse_m3u(content)
            else:
                channels = self._parse_txt_live(content)
        except Exception as e:
            print(f"[SourceManager] 拉取直播源失败: {e}")
        return channels

    def _parse_m3u(self, content: str) -> list:
        """解析 M3U 直播源"""
        channels = []
        lines = content.split('\n')
        current_name = ''
        current_group = ''

        for line in lines:
            line = line.strip()
            if line.startswith('#EXTINF:'):
                group_match = re.search(r'group-title="([^"]*)"', line)
                current_group = group_match.group(1) if group_match else ''
                name_match = re.search(r',(.+)$', line)
                current_name = name_match.group(1).strip() if name_match else '未知频道'
            elif line and not line.startswith('#'):
                if current_name:
                    # 检查是否已有同名频道
                    existing = next((c for c in channels if c.name == current_name), None)
                    if existing:
                        existing.urls.append(line)
                    else:
                        channels.append(LiveChannel(
                            name=current_name,
                            urls=[line],
                            group=current_group
                        ))
                    current_name = ''
        return channels

    def _parse_txt_live(self, content: str) -> list:
        """解析 TXT 格式直播源"""
        channels = []
        current_group = ''

        for line in content.split('\n'):
            line = line.strip()
            if not line:
                continue
            if '#genre#' in line:
                current_group = line.split(',')[0].strip()
                continue
            if ',' in line:
                parts = line.split(',', 1)
                name = parts[0].strip()
                url = parts[1].strip()
                if name and url.startswith('http'):
                    channels.append(LiveChannel(
                        name=name,
                        urls=[url],
                        group=current_group
                    ))
        return channels
