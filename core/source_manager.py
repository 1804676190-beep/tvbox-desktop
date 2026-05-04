#!/usr/bin/env python3
"""TVBox Desktop — 订阅源管理器（多仓版）

支持 TVBox 生态中的所有主要接口格式:
- 多仓格式: {urls: [{url, name}, ...]} — 包含多个单源的集合
- 单源格式: {sites, lives, parses, ...} — 直接可用的接口
- XML 格式: <?xml ...><video> — 苹果CMS等传统接口
- M3U/TXT 直播源: #EXTINF ... 或 name,url 格式

站点类型 (type):
- type 0: XML API（如苹果CMS）
- type 1: JSON API（标准采集站）
- type 3: Spider（需要 JS/Jar 执行）
- type 4: 嗅探（需要 webview 嗅探真实播放地址）

关键改进:
- 智能判断源类型（多仓/单源/直播）
- 并行加载（QThread 信号）
- 源健康检查
- 错误恢复（单个源失败不影响其他源）
- 缓存机制
"""

import re
import json
import time
import requests
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from core.models import VideoItem, LiveChannel, Category, SourceInfo
from core.spider_engine import SpiderEngine


# ============================================================
#  源类型枚举
# ============================================================
SOURCE_TYPE_MULTI = "multi"      # 多仓（包含多个单源 URL）
SOURCE_TYPE_SINGLE = "single"    # 单源（直接可用的 TVBox JSON）
SOURCE_TYPE_XML = "xml"          # XML API（苹果CMS等）
SOURCE_TYPE_LIVE = "live"        # 直播源（M3U/TXT）
SOURCE_TYPE_UNKNOWN = "unknown"  # 未知格式


# ============================================================
#  源解析结果
# ============================================================
@dataclass
class SourceResult:
    """源解析结果"""
    source_type: str = SOURCE_TYPE_UNKNOWN
    name: str = ""
    url: str = ""
    # 单源字段
    sites: list = field(default_factory=list)           # [{key, name, type, api, ...}]
    categories: list = field(default_factory=list)       # [Category]
    live_channels: list = field(default_factory=list)    # [LiveChannel]
    parses: list = field(default_factory=list)           # [{name, url, ...}]
    spider: str = ""                                     # Spider 脚本路径
    flags: list = field(default_factory=list)
    ijk: dict = field(default_factory=dict)
    ads: list = field(default_factory=list)
    # 多仓字段
    urls: list = field(default_factory=list)             # [{url, name}]
    # 状态
    healthy: bool = True
    error: str = ""
    load_time: float = 0.0

    def to_dict(self):
        """转换为字典（用于缓存和序列化）"""
        d = {
            "source_type": self.source_type,
            "name": self.name,
            "url": self.url,
            "sites": self.sites,
            "live_channels": [c.to_dict() if hasattr(c, 'to_dict') else c for c in self.live_channels],
            "parses": self.parses,
            "spider": self.spider,
            "flags": self.flags,
            "ijk": self.ijk,
            "ads": self.ads,
            "urls": self.urls,
            "healthy": self.healthy,
            "error": self.error,
            "load_time": self.load_time,
        }
        return d


# ============================================================
#  源管理器
# ============================================================
class SourceManager:
    """
    订阅源管理器 — 拉取、解析、搜索、缓存
    
    支持 TVBox 全部接口格式，自动识别源类型并智能处理。
    通过 spider_engine 支持 type=3 的 JS/Jar 站点。
    """

    def __init__(self, spider_engine: SpiderEngine = None):
        """
        初始化源管理器
        
        Args:
            spider_engine: Spider 引擎实例（可选，用于 type=3 站点）
        """
        self.spider_engine = spider_engine or SpiderEngine()
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        })
        self.session.verify = False

        # 缓存: url -> SourceResult
        self._source_cache: Dict[str, SourceResult] = {}
        # 缓存: api_url -> 分类列表
        self._api_cache: Dict[str, list] = {}
        # 缓存过期时间（秒）
        self._cache_ttl = 600  # 10 分钟
        self._cache_time: Dict[str, float] = {}
        # 当前源的 spider URL（type=3 站点需要）
        self._current_spider_url: str = ""

    # ========================================================
    #  缓存管理
    # ========================================================

    def _get_cached(self, key: str):
        """获取缓存（检查是否过期）"""
        if key in self._source_cache:
            cached_time = self._cache_time.get(key, 0)
            if time.time() - cached_time < self._cache_ttl:
                return self._source_cache[key]
            else:
                # 过期，清除
                del self._source_cache[key]
                self._cache_time.pop(key, None)
        return None

    def _set_cached(self, key: str, value):
        """设置缓存"""
        self._source_cache[key] = value
        self._cache_time[key] = time.time()

    def clear_cache(self):
        """清除所有缓存"""
        self._source_cache.clear()
        self._api_cache.clear()
        self._cache_time.clear()

    # ========================================================
    #  源类型判断
    # ========================================================

    @staticmethod
    def detect_source_type(data: Any, content: str = "") -> str:
        """
        智能判断源类型
        
        Args:
            data: 解析后的 JSON 数据（可能是 dict/list/None）
            content: 原始文本内容
            
        Returns:
            源类型字符串
        """
        # 1. 检查是否为 M3U 直播源
        if content and ('#EXTINF' in content[:1000] or '#EXTM3U' in content[:1000]):
            return SOURCE_TYPE_LIVE

        # 2. 检查是否为 TXT 直播源（name,url 格式，且没有 JSON 结构）
        if content and not isinstance(data, (dict, list)):
            lines = content.strip().split('\n')
            if len(lines) > 3:
                comma_count = sum(1 for line in lines[:10] if ',' in line and 'http' in line.lower())
                if comma_count >= 3:
                    return SOURCE_TYPE_LIVE

        # 3. 检查是否为 XML
        if content and (content.strip().startswith('<?xml') or '<video' in content[:500]):
            return SOURCE_TYPE_XML

        # 4. JSON 格式判断
        if isinstance(data, dict):
            # 多仓格式: 包含 urls 数组
            if 'urls' in data and isinstance(data['urls'], list):
                return SOURCE_TYPE_MULTI

            # 单源格式: 包含 sites 或 lives
            if 'sites' in data or 'lives' in data:
                return SOURCE_TYPE_SINGLE

            # 兼容: storeHouse 格式（仓库格式，不是源格式）
            if 'storeHouse' in data:
                return SOURCE_TYPE_UNKNOWN

        # 5. JSON 数组（可能是仓库列表，不是源）
        if isinstance(data, list):
            return SOURCE_TYPE_UNKNOWN

        return SOURCE_TYPE_UNKNOWN

    # ========================================================
    #  核心接口: 拉取并解析源
    # ========================================================

    def fetch_source(self, source: SourceInfo) -> SourceResult:
        """
        拉取并解析订阅源
        
        根据源内容自动判断类型:
        - 多仓: 返回 urls 列表（不展开）
        - 单源: 解析 sites, lives, parses, categories
        - XML: 解析为分类和视频列表
        - 直播: 解析为频道列表
        
        Args:
            source: 源信息
            
        Returns:
            SourceResult 解析结果
        """
        start_time = time.time()

        # 检查缓存
        cached = self._get_cached(source.url)
        if cached:
            return cached

        result = SourceResult(name=source.name, url=source.url)

        try:
            # 拉取内容
            resp = self.session.get(source.url, timeout=15)
            resp.raise_for_status()
            content = resp.text.strip()
        except requests.exceptions.Timeout:
            result.error = "请求超时"
            result.healthy = False
            result.load_time = time.time() - start_time
            return result
        except requests.exceptions.ConnectionError:
            result.error = "连接失败"
            result.healthy = False
            result.load_time = time.time() - start_time
            return result
        except Exception as e:
            result.error = f"拉取失败: {str(e)}"
            result.healthy = False
            result.load_time = time.time() - start_time
            return result

        # 尝试 JSON 解析
        data = None
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            pass

        # 判断源类型
        result.source_type = self.detect_source_type(data, content)

        # 根据类型分别处理
        try:
            if result.source_type == SOURCE_TYPE_MULTI:
                self._parse_multi_source(data, result)
            elif result.source_type == SOURCE_TYPE_SINGLE:
                self._parse_single_source(data, result, source.url)
            elif result.source_type == SOURCE_TYPE_XML:
                self._parse_xml_source(content, result)
            elif result.source_type == SOURCE_TYPE_LIVE:
                self._parse_live_source(content, result)
            else:
                result.error = "无法识别的源格式"
                result.healthy = False
        except Exception as e:
            result.error = f"解析失败: {str(e)}"
            result.healthy = False

        result.load_time = time.time() - start_time

        # 缓存结果
        if result.healthy:
            self._set_cached(source.url, result)

        return result

    # ========================================================
    #  多仓解析
    # ========================================================

    def _parse_multi_source(self, data: dict, result: SourceResult):
        """
        解析多仓格式
        
        多仓返回 urls 列表，每个 url 指向一个单源。
        调用方可遍历 urls 逐个拉取。
        """
        urls = data.get('urls', [])
        if not urls:
            result.error = "多仓格式缺少 urls 字段"
            result.healthy = False
            return

        result.urls = []
        for item in urls:
            if isinstance(item, dict):
                url = item.get('url', '').strip()
                name = item.get('name', '').strip() or '未命名源'
            elif isinstance(item, str):
                url = item.strip()
                name = '未命名源'
            else:
                continue

            if url:
                result.urls.append({"url": url, "name": name})

        if not result.urls:
            result.error = "多仓中没有有效的源 URL"
            result.healthy = False

    # ========================================================
    #  单源解析
    # ========================================================

    def _parse_single_source(self, data: dict, result: SourceResult, base_url: str = ""):
        """
        解析单源格式
        
        提取 sites, lives, parses 等字段，
        并尝试拉取第一个可用 API 站点的分类列表。
        """
        # 基础字段
        result.spider = data.get('spider', '')
        result.sites = data.get('sites', [])
        result.parses = data.get('parses', [])
        result.flags = data.get('flags', [])
        result.ijk = data.get('ijk', {})
        result.ads = data.get('ads', [])

        # 保存当前 spider URL 供后续 type=3 站点使用
        self._current_spider_url = result.spider

        # 解析直播源
        for live in data.get('lives', []):
            live_url = live.get('url', '')
            live_name = live.get('name', '直播')
            if live_url:
                channels = self._fetch_live_channels(live_url)
                result.live_channels.extend(channels)

        # 尝试从第一个可用站点拉取分类
        categories = self._fetch_categories_from_sites(result.sites)
        result.categories = categories

    def _fetch_categories_from_sites(self, sites: list) -> list:
        """从站点列表中找到第一个可用的 API 站点并拉取分类"""
        categories = []
        for site in sites:
            site_type = site.get('type', -1)
            api_url = site.get('api', '')
            if not api_url:
                continue

            # 只处理 type 0/1（标准 API）的站点来获取分类
            if site_type in (0, 1):
                cats = self.fetch_categories(site)
                if cats:
                    categories.extend(cats)
                    break  # 找到一个可用的就够了
        return categories

    # ========================================================
    #  XML 源解析
    # ========================================================

    def _parse_xml_source(self, content: str, result: SourceResult):
        """解析 XML 格式源（苹果CMS等）"""
        from bs4 import BeautifulSoup
        try:
            soup = BeautifulSoup(content, 'html.parser')
            categories = []

            # 提取分类
            for type_elem in soup.find_all('type'):
                type_id = type_elem.get('id', '')
                type_name = type_elem.get_text(strip=True) or type_elem.string or ''
                if type_id:
                    categories.append(Category(
                        name=type_name,
                        type_id=str(type_id),
                        items=[]
                    ))

            # 提取视频列表
            for video in soup.find_all('video'):
                vod_name = ''
                vod_pic = ''
                vod_id = ''

                name_elem = video.find('name')
                if name_elem:
                    vod_name = name_elem.get_text(strip=True)

                pic_elem = video.find('pic')
                if pic_elem:
                    vod_pic = pic_elem.get_text(strip=True)

                id_elem = video.find('id')
                if id_elem:
                    vod_id = id_elem.get_text(strip=True)

                if vod_name:
                    # 找到对应的分类
                    type_elem = video.find('type')
                    type_id = type_elem.get_text(strip=True) if type_elem else ''

                    item = VideoItem(
                        name=vod_name,
                        url=vod_id,
                        pic=vod_pic,
                    )

                    # 添加到对应分类
                    for cat in categories:
                        if cat.type_id == type_id:
                            cat.items.append(item)
                            break
                    else:
                        # 没有匹配分类，添加到"其他"
                        if not categories:
                            categories.append(Category(name="其他", type_id="0"))
                        categories[-1].items.append(item)

            result.categories = categories

        except Exception as e:
            result.error = f"XML 解析失败: {str(e)}"
            result.healthy = False

    # ========================================================
    #  直播源解析
    # ========================================================

    def _parse_live_source(self, content: str, result: SourceResult):
        """解析直播源（M3U/TXT）"""
        if '#EXTINF' in content or '#EXTM3U' in content:
            result.live_channels = self._parse_m3u(content)
        else:
            result.live_channels = self._parse_txt_live(content)

    def _fetch_live_channels(self, live_url: str) -> list:
        """拉取并解析远程直播源"""
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
        """解析 M3U 格式直播源"""
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

    # ========================================================
    #  站点 API 接口
    # ========================================================

    def _get_site_api_url(self, site: dict) -> str:
        """获取站点的 API 地址（支持相对路径和绝对路径）"""
        api = site.get('api', '')
        if not api:
            return ''
        # 如果是相对路径，尝试从 site 的 url 字段推断
        if api.startswith('./') or api.startswith('../'):
            # 相对路径，需要结合 spider 路径
            return api
        return api

    def fetch_categories(self, site: dict) -> list:
        """
        获取站点分类列表
        
        Args:
            site: 站点配置字典 {key, name, type, api, ...}
            
        Returns:
            Category 列表
        """
        site_type = site.get('type', -1)
        api_url = self._get_site_api_url(site)

        if not api_url:
            return []

        # 检查缓存
        cache_key = f"cats:{api_url}"
        if cache_key in self._api_cache:
            return self._api_cache[cache_key]

        categories = []

        if site_type in (0, 1):
            # type 0/1: 直接调用 API
            categories = self._fetch_categories_api(api_url)
        elif site_type == 3:
            # type 3: 通过 Spider 引擎
            categories = self._fetch_categories_spider(site)
        elif site_type == 4:
            # type 4: 嗅探类型，通常没有分类 API
            pass

        # 缓存结果
        if categories:
            self._api_cache[cache_key] = categories

        return categories

    def _fetch_categories_api(self, api_url: str) -> list:
        """通过标准 API 拉取分类列表"""
        # 跳过 csp_ 开头的类名（这些是 spider，不是 URL）
        if api_url.startswith('csp_'):
            return []
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
                    cat = Category(name=type_name, type_id=str(type_id), items=[])
                    categories.append(cat)
        except Exception as e:
            print(f"[SourceManager] 拉取分类失败 [{api_url}]: {e}")
        return categories

    def _fetch_categories_spider(self, site: dict) -> list:
        """通过 Spider 引擎获取分类（type=3）"""
        categories = []
        if not self.spider_engine:
            return categories

        try:
            result = self.spider_engine.call_site_method(
                site, self._current_spider_url, 'homeContent', filter=True
            )
            if result and isinstance(result, dict):
                for cls in result.get('class', []):
                    type_id = cls.get('type_id', '')
                    type_name = cls.get('type_name', '')
                    if type_id:
                        categories.append(Category(name=type_name, type_id=str(type_id), items=[]))
        except Exception as e:
            print(f"[SourceManager] Spider 获取分类失败: {e}")

        return categories

    def fetch_category_items(self, site: dict, tid: str, pg: int = 1) -> list:
        """
        获取分类下的视频列表
        
        Args:
            site: 站点配置
            tid: 分类 ID
            pg: 页码
            
        Returns:
            VideoItem 列表
        """
        site_type = site.get('type', -1)
        api_url = self._get_site_api_url(site)

        if not api_url:
            return []

        if site_type in (0, 1):
            return self._fetch_category_items_api(api_url, tid, pg)
        elif site_type == 3:
            return self._fetch_category_items_spider(site, tid, pg)
        return []

    def _fetch_category_items_api(self, api_url: str, tid: str, pg: int = 1) -> list:
        """通过标准 API 拉取分类下的视频列表"""
        # 跳过 csp_ 开头的类名
        if api_url.startswith('csp_'):
            return []
        items = []
        try:
            url = api_url.rstrip('/') + f'?ac=list&t={tid}&pg={pg}'
            resp = self.session.get(url, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            for vod in data.get('list', []):
                item = self._vod_to_video_item(vod)
                if item.name:
                    items.append(item)
        except Exception as e:
            print(f"[SourceManager] 拉取分类内容失败: {e}")
        return items

    def _fetch_category_items_spider(self, site: dict, tid: str, pg: int = 1) -> list:
        """通过 Spider 引擎获取分类下的视频列表"""
        items = []
        if not self.spider_engine:
            return items

        try:
            result = self.spider_engine.call_site_method(
                site, self._current_spider_url, 'category',
                tid=tid, pg=pg, filter=True
            )
            if result and isinstance(result, dict):
                for vod in result.get('list', []):
                    item = self._vod_to_video_item(vod)
                    if item.name:
                        items.append(item)
        except Exception as e:
            print(f"[SourceManager] Spider 获取分类内容失败: {e}")

        return items

    def fetch_detail(self, site, vod_id: str) -> Optional[VideoItem]:
        """
        获取视频详情（含多线路播放地址）
        
        Args:
            site: 站点配置 dict 或 API URL 字符串（向后兼容）
            vod_id: 视频 ID
            
        Returns:
            VideoItem 或 None
        """
        # 向后兼容：如果传入的是字符串 URL，构造 site dict
        if isinstance(site, str):
            site = {'type': 0, 'api': site, 'key': 'default', 'name': '默认'}

        site_type = site.get('type', -1)
        api_url = self._get_site_api_url(site)

        if not api_url:
            return None

        if site_type in (0, 1):
            return self._fetch_detail_api(api_url, vod_id)
        elif site_type == 3:
            return self._fetch_detail_spider(site, vod_id)
        # 默认尝试 API 方式
        return self._fetch_detail_api(api_url, vod_id)

    def _fetch_detail_api(self, api_url: str, vod_id: str) -> Optional[VideoItem]:
        """通过标准 API 获取视频详情"""
        # 跳过 csp_ 开头的类名（这些是 spider，不是 URL）
        if api_url.startswith('csp_'):
            return None
        try:
            url = api_url.rstrip('/') + f'?ac=detail&ids={vod_id}'
            resp = self.session.get(url, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            vod_list = data.get('list', [])
            if not vod_list:
                return None

            vod = vod_list[0]
            video = self._vod_to_video_item(vod, detail=True)
            return video
        except Exception as e:
            print(f"[SourceManager] 获取详情失败: {e}")
            return None

    def _fetch_detail_spider(self, site: dict, vod_id: str) -> Optional[VideoItem]:
        """通过 Spider 引擎获取视频详情"""
        if not self.spider_engine:
            return None

        try:
            result = self.spider_engine.call_site_method(
                site, self._current_spider_url, 'detail', ids=vod_id
            )
            if result and isinstance(result, dict):
                vod_list = result.get('list', [])
                if vod_list:
                    return self._vod_to_video_item(vod_list[0], detail=True)
        except Exception as e:
            print(f"[SourceManager] Spider 获取详情失败: {e}")

        return None

    def search(self, site, keyword: str) -> list:
        """
        搜索影视
        
        Args:
            site: 站点配置 dict 或 API URL 字符串（向后兼容）
            keyword: 搜索关键词
            
        Returns:
            VideoItem 列表
        """
        # 向后兼容：如果传入的是字符串 URL，构造 site dict
        if isinstance(site, str):
            site = {'type': 0, 'api': site, 'key': 'default', 'name': '默认'}

        site_type = site.get('type', -1)
        api_url = self._get_site_api_url(site)

        if not api_url:
            return []

        if site_type in (0, 1):
            return self._search_api(api_url, keyword)
        elif site_type == 3:
            return self._search_spider(site, keyword)
        # 默认尝试 API 方式
        return self._search_api(api_url, keyword)

    def _search_api(self, api_url: str, keyword: str) -> list:
        """通过标准 API 搜索"""
        # 跳过 csp_ 开头的类名
        if api_url.startswith('csp_'):
            return []
        items = []
        try:
            url = api_url.rstrip('/') + f'?ac=detail&wd={keyword}'
            resp = self.session.get(url, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            for vod in data.get('list', []):
                item = self._vod_to_video_item(vod)
                if item.name:
                    items.append(item)
        except Exception as e:
            print(f"[SourceManager] 搜索失败: {e}")
        return items

    def _search_spider(self, site: dict, keyword: str) -> list:
        """通过 Spider 引擎搜索"""
        items = []
        if not self.spider_engine:
            return items

        try:
            result = self.spider_engine.call_site_method(
                site, self._current_spider_url, 'search', wd=keyword
            )
            if result and isinstance(result, dict):
                for vod in result.get('list', []):
                    item = self._vod_to_video_item(vod)
                    if item.name:
                        items.append(item)
        except Exception as e:
            print(f"[SourceManager] Spider 搜索失败: {e}")

        return items

    def resolve_play_url(self, site: dict, flag: str, url: str) -> str:
        """
        解析播放地址
        
        对于 type=3 的站点，需要通过 Spider 引擎的 play 接口解析。
        对于 type=4 的站点，返回原始 URL（由外部 webview 嗅探）。
        对于 type=0/1，直接返回 URL。
        
        Args:
            site: 站点配置
            flag: 播放源标识
            url: 原始播放地址
            
        Returns:
            解析后的真实播放地址
        """
        site_type = site.get('type', -1)

        if site_type in (0, 1):
            # 标准 API，直接返回
            return url
        elif site_type == 3:
            # Spider 类型，需要通过引擎解析
            return self._resolve_play_url_spider(site, flag, url)
        elif site_type == 4:
            # 嗅探类型，返回原始 URL（由外部处理）
            return url
        return url

    def _resolve_play_url_spider(self, site: dict, flag: str, url: str) -> str:
        """通过 Spider 引擎解析播放地址"""
        if not self.spider_engine:
            return url

        try:
            result = self.spider_engine.call_site_method(
                site, self._current_spider_url, 'play', flag=flag, id=url
            )
            if result and isinstance(result, dict):
                return result.get('url', url)
        except Exception as e:
            print(f"[SourceManager] Spider 解析播放地址失败: {e}")

        return url

    # ========================================================
    #  辅助方法
    # ========================================================

    def _vod_to_video_item(self, vod: dict, detail: bool = False) -> VideoItem:
        """
        将 API 返回的 vod 字典转换为 VideoItem
        
        Args:
            vod: API 返回的视频数据字典
            detail: 是否为详情模式（解析播放线路）
            
        Returns:
            VideoItem 实例
        """
        video = VideoItem(
            name=vod.get('vod_name', ''),
            url=str(vod.get('vod_id', '')),
            pic=vod.get('vod_pic', ''),
            group=vod.get('type_name', ''),
            description=vod.get('vod_content', '') if detail else '',
            year=vod.get('vod_year', ''),
            area=vod.get('vod_area', ''),
            type_name=vod.get('type_name', ''),
            director=vod.get('vod_director', ''),
            actor=vod.get('vod_actor', ''),
        )

        if detail:
            # 解析多线路播放地址
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

    def _parse_episodes(self, play_url: str) -> list:
        """
        解析剧集列表
        
        格式: 集名$url#集名$url#...
        """
        episodes = []
        parts = play_url.split('#')
        for part in parts:
            if '$' in part:
                ep_name, ep_url = part.split('$', 1)
                ep_name = ep_name.strip()
                ep_url = ep_url.strip()
                if ep_url and ep_name:
                    episodes.append({'name': ep_name, 'url': ep_url})
        return episodes

    # ========================================================
    #  源健康检查
    # ========================================================

    def check_source_health(self, source: SourceInfo) -> dict:
        """
        检查源是否可用
        
        Args:
            source: 源信息
            
        Returns:
            {healthy: bool, latency: float, error: str}
        """
        start = time.time()
        try:
            resp = self.session.get(source.url, timeout=10, stream=True)
            # 只读取前 1KB 来检查是否可达
            resp.raw.read(1024)
            resp.close()
            latency = time.time() - start
            return {
                'healthy': resp.status_code == 200,
                'latency': round(latency, 3),
                'error': '' if resp.status_code == 200 else f'HTTP {resp.status_code}',
            }
        except requests.exceptions.Timeout:
            return {'healthy': False, 'latency': 10.0, 'error': '超时'}
        except requests.exceptions.ConnectionError:
            return {'healthy': False, 'latency': time.time() - start, 'error': '连接失败'}
        except Exception as e:
            return {'healthy': False, 'latency': time.time() - start, 'error': str(e)}

    def check_sources_health(self, sources: list) -> list:
        """
        批量检查多个源的健康状态
        
        Args:
            sources: SourceInfo 列表
            
        Returns:
            [{source: SourceInfo, healthy, latency, error}, ...]
        """
        results = []
        for source in sources:
            health = self.check_source_health(source)
            results.append({
                'source': source,
                **health,
            })
        return results

    # ========================================================
    #  并行加载支持（供 QThread 调用）
    # ========================================================

    def fetch_source_with_progress(self, source: SourceInfo, progress_callback=None) -> SourceResult:
        """
        拉取源并报告进度（供 QThread 使用）
        
        Args:
            source: 源信息
            progress_callback: 进度回调 fn(current, total, message)
            
        Returns:
            SourceResult
        """
        if progress_callback:
            progress_callback(0, 1, f"正在加载: {source.name}")

        result = self.fetch_source(source)

        if progress_callback:
            if result.healthy:
                progress_callback(1, 1, f"加载完成: {source.name}")
            else:
                progress_callback(1, 1, f"加载失败: {source.name} - {result.error}")

        return result

    def fetch_multi_source_with_progress(self, source: SourceInfo, progress_callback=None) -> list:
        """
        拉取多仓源并逐个解析其中的单源（供 QThread 使用）
        
        Args:
            source: 多仓源信息
            progress_callback: 进度回调 fn(current, total, message)
            
        Returns:
            [SourceResult, ...] 每个单源的解析结果
        """
        # 先拉取多仓
        multi_result = self.fetch_source(source)

        if multi_result.source_type != SOURCE_TYPE_MULTI:
            # 不是多仓，直接返回
            return [multi_result]

        if not multi_result.healthy:
            return [multi_result]

        # 逐个拉取多仓中的单源
        results = []
        total = len(multi_result.urls)

        for i, url_info in enumerate(multi_result.urls):
            if progress_callback:
                progress_callback(i, total, f"加载源 [{i+1}/{total}]: {url_info['name']}")

            sub_source = SourceInfo(
                name=url_info['name'],
                url=url_info['url'],
                source_type='json',
            )
            sub_result = self.fetch_source(sub_source)
            results.append(sub_result)

        if progress_callback:
            progress_callback(total, total, f"多仓加载完成，共 {total} 个源")

        return results
