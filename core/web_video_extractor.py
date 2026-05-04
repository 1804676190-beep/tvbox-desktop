#!/usr/bin/env python3
"""TVBox Desktop — 网页视频资源提取器

自动识别网页中的视频资源 (m3u8, mp4, flv 等)，
提取播放地址并转为 TVBox 可用的线路格式。

用法:
    from core.web_video_extractor import WebVideoExtractor
    extractor = WebVideoExtractor()
    sources = extractor.extract("https://example.com/play/123")
    # sources: [{name, url, type, headers}]
"""

import re
import json
import base64
import requests
from typing import List, Dict, Optional
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse, parse_qs, unquote


@dataclass
class VideoSource:
    """提取的视频源"""
    name: str           # 来源名称
    url: str            # 播放地址
    quality: str = ""   # 清晰度 (标清/高清/超清/4K)
    headers: dict = None  # 自定义请求头
    source_type: str = "m3u8"  # m3u8 / mp4 / flv

    def __post_init__(self):
        if self.headers is None:
            self.headers = {}

    def to_tvbox_source(self) -> dict:
        """转为 TVBox 线路格式"""
        return {
            "name": self.name,
            "url": self.url,
            "type": self.source_type,
            "headers": self.headers,
        }


class WebVideoExtractor:
    """网页视频资源提取器"""

    # 常见视频 URL 正则模式
    VIDEO_PATTERNS = [
        # M3U8 直链
        r'(?:https?:)?//[^\s"\'<>]+\.m3u8[^\s"\'<>]*',
        # MP4 直链
        r'(?:https?:)?//[^\s"\'<>]+\.mp4[^\s"\'<>]*',
        # FLV 直链
        r'(?:https?:)?//[^\s"\'<>]+\.flv[^\s"\'<>]*',
        # TS 直链
        r'(?:https?:)?//[^\s"\'<>]+\.ts[^\s"\'<>]*',
    ]

    # 播放器 JS 中常见的变量名
    JS_VAR_PATTERNS = [
        # 常见播放器变量
        r'(?:url|src|video_url|playurl|play_url|file|source)\s*[:=]\s*["\']([^"\']+\.(?:m3u8|mp4|flv|ts)[^"\']*)["\']',
        # JSON 配置
        r'"(?:url|src|file|source)"\s*:\s*"([^"]+\.(?:m3u8|mp4|flv|ts)[^"]*)"',
        # 加密/编码的 URL (base64)
        r'(?:url|src|video_url)\s*[:=]\s*["\']([A-Za-z0-9+/=]{20,})["\']',
    ]

    # 常见混淆/加密模式
    OBFUSCATION_PATTERNS = [
        # base64 编码的 URL
        r'atob\s*\(\s*["\']([A-Za-z0-9+/=]+)["\']',
        r'base64_decode\s*\(\s*["\']([A-Za-z0-9+/=]+)["\']',
        # eval 解密
        r'eval\s*\(\s*function\s*\(\s*p\s*,\s*a\s*,\s*c\s*,\s*k\s*,\s*e\s*,\s*[dr]\s*\)',
    ]

    # 需要排除的广告/追踪域名
    EXCLUDE_DOMAINS = {
        'google.com', 'googlesyndication.com', 'doubleclick.net',
        'facebook.com', 'twitter.com', 'analytics', 'tracking',
        'ads.', 'ad.', 'pixel.', 'beacon.',
        'cnzz.com', 'baidu.com/hm', '51.la',
    }

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        })
        self.session.verify = False

    def extract(self, url: str, deep: bool = True) -> List[VideoSource]:
        """
        从网页 URL 提取视频资源

        参数:
            url: 网页地址
            deep: 是否深度提取 (解析 iframe、JS 等)

        返回:
            去重后的视频源列表
        """
        sources = []

        try:
            resp = self.session.get(url, timeout=15)
            resp.raise_for_status()
            html = resp.text
            page_url = resp.url  # 处理重定向
        except Exception as e:
            print(f"[WebVideoExtractor] 获取页面失败: {e}")
            return sources

        # 1. 直接从 HTML 提取视频 URL
        sources.extend(self._extract_from_text(html, page_url))

        # 2. 从 JS 变量提取
        sources.extend(self._extract_from_js(html, page_url))

        # 3. 从 JSON-LD / og:video 提取
        sources.extend(self._extract_from_meta(html, page_url))

        # 4. 深度提取: 解析 iframe
        if deep:
            sources.extend(self._extract_from_iframes(html, page_url))

        # 5. 尝试解密混淆内容
        sources.extend(self._extract_from_obfuscation(html, page_url))

        # 去重
        sources = self._deduplicate(sources)

        # 过滤广告
        sources = [s for s in sources if not self._is_ad_url(s.url)]

        return sources

    def _extract_from_text(self, html: str, base_url: str) -> List[VideoSource]:
        """从 HTML 文本直接提取视频 URL"""
        sources = []
        for pattern in self.VIDEO_PATTERNS:
            for match in re.finditer(pattern, html, re.IGNORECASE):
                url = match.group(0)
                if url.startswith('//'):
                    url = 'https:' + url
                url = self._normalize_url(url, base_url)
                if self._is_valid_video_url(url):
                    sources.append(VideoSource(
                        name=self._guess_quality(url),
                        url=url,
                        source_type=self._guess_type(url),
                    ))
        return sources

    def _extract_from_js(self, html: str, base_url: str) -> List[VideoSource]:
        """从 JavaScript 变量提取视频 URL"""
        sources = []

        # 提取所有 <script> 标签内容
        script_blocks = re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL | re.IGNORECASE)

        for script in script_blocks:
            for pattern in self.JS_VAR_PATTERNS:
                for match in re.finditer(pattern, script, re.IGNORECASE):
                    value = match.group(1)

                    # 尝试 base64 解码
                    decoded = self._try_base64_decode(value)
                    if decoded and self._is_valid_video_url(decoded):
                        sources.append(VideoSource(
                            name=self._guess_quality(decoded),
                            url=decoded,
                            source_type=self._guess_type(decoded),
                        ))
                        continue

                    # 普通 URL
                    url = self._normalize_url(value, base_url)
                    if self._is_valid_video_url(url):
                        sources.append(VideoSource(
                            name=self._guess_quality(url),
                            url=url,
                            source_type=self._guess_type(url),
                        ))

        return sources

    def _extract_from_meta(self, html: str, base_url: str) -> List[VideoSource]:
        """从 meta 标签 (og:video, JSON-LD) 提取"""
        sources = []

        # og:video
        og_video = re.findall(r'<meta[^>]+property=["\']og:video["\'][^>]+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
        for url in og_video:
            url = self._normalize_url(url, base_url)
            if self._is_valid_video_url(url):
                sources.append(VideoSource(name="og:video", url=url, source_type=self._guess_type(url)))

        # og:video:url
        og_video_url = re.findall(r'<meta[^>]+property=["\']og:video:url["\'][^>]+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
        for url in og_video_url:
            url = self._normalize_url(url, base_url)
            if self._is_valid_video_url(url):
                sources.append(VideoSource(name="og:video:url", url=url, source_type=self._guess_type(url)))

        # JSON-LD
        jsonld_blocks = re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.DOTALL | re.IGNORECASE)
        for block in jsonld_blocks:
            try:
                data = json.loads(block)
                if isinstance(data, dict):
                    content_url = data.get("contentUrl", "")
                    embed_url = data.get("embedUrl", "")
                    for url in [content_url, embed_url]:
                        if url:
                            url = self._normalize_url(url, base_url)
                            if self._is_valid_video_url(url):
                                sources.append(VideoSource(name="JSON-LD", url=url, source_type=self._guess_type(url)))
            except json.JSONDecodeError:
                pass

        return sources

    def _extract_from_iframes(self, html: str, base_url: str) -> List[VideoSource]:
        """解析 iframe 嵌套的播放器"""
        sources = []
        iframes = re.findall(r'<iframe[^>]+src=["\']([^"\']+)["\']', html, re.IGNORECASE)

        for iframe_url in iframes:
            iframe_url = self._normalize_url(iframe_url, base_url)

            # 跳过广告 iframe
            if self._is_ad_url(iframe_url):
                continue

            try:
                resp = self.session.get(iframe_url, timeout=10)
                resp.raise_for_status()
                iframe_html = resp.text

                # 递归提取 (但不继续深入, 防止无限递归)
                sources.extend(self._extract_from_text(iframe_html, iframe_url))
                sources.extend(self._extract_from_js(iframe_html, iframe_url))

            except Exception:
                pass

        return sources

    def _extract_from_obfuscation(self, html: str, base_url: str) -> List[VideoSource]:
        """尝试解密混淆的视频地址"""
        sources = []

        for pattern in self.OBFUSCATION_PATTERNS:
            for match in re.finditer(pattern, html, re.IGNORECASE):
                if 'eval' in pattern:
                    # eval 解密 — 提取其中的字符串常量
                    eval_block = match.group(0)
                    strings = re.findall(r'["\']([^"\']{10,})["\']', eval_block)
                    for s in strings:
                        decoded = self._try_base64_decode(s)
                        if decoded and self._is_valid_video_url(decoded):
                            sources.append(VideoSource(
                                name="解密",
                                url=decoded,
                                source_type=self._guess_type(decoded),
                            ))
                else:
                    # base64 直接解码
                    encoded = match.group(1)
                    decoded = self._try_base64_decode(encoded)
                    if decoded and self._is_valid_video_url(decoded):
                        sources.append(VideoSource(
                            name="Base64",
                            url=decoded,
                            source_type=self._guess_type(decoded),
                        ))

        return sources

    # ============================================================
    #  工具方法
    # ============================================================

    def _normalize_url(self, url: str, base_url: str) -> str:
        """规范化 URL"""
        if url.startswith('//'):
            url = 'https:' + url
        elif url.startswith('/'):
            parsed = urlparse(base_url)
            url = f"{parsed.scheme}://{parsed.netloc}{url}"
        elif not url.startswith('http'):
            url = urljoin(base_url, url)
        return url.strip()

    def _is_valid_video_url(self, url: str) -> bool:
        """判断是否为有效视频 URL"""
        if not url or len(url) < 10:
            return False
        parsed = urlparse(url)
        if not parsed.scheme in ('http', 'https'):
            return False
        # 检查是否包含视频扩展名或特征
        lower = url.lower()
        video_indicators = ['.m3u8', '.mp4', '.flv', '.ts', '/video/', '/play/', 'video_url', 'playurl']
        return any(ind in lower for ind in video_indicators)

    def _is_ad_url(self, url: str) -> bool:
        """判断是否为广告 URL"""
        lower = url.lower()
        return any(domain in lower for domain in self.EXCLUDE_DOMAINS)

    def _guess_type(self, url: str) -> str:
        """猜测视频类型"""
        lower = url.lower()
        if '.m3u8' in lower:
            return 'm3u8'
        elif '.mp4' in lower:
            return 'mp4'
        elif '.flv' in lower:
            return 'flv'
        elif '.ts' in lower:
            return 'ts'
        return 'm3u8'  # 默认 m3u8

    def _guess_quality(self, url: str) -> str:
        """根据 URL 猜测清晰度"""
        lower = url.lower()
        if '4k' in lower or '2160' in lower:
            return '4K'
        elif '1080' in lower or 'fhd' in lower:
            return '1080P'
        elif '720' in lower or 'hd' in lower:
            return '720P'
        elif '480' in lower or 'sd' in lower:
            return '标清'
        return '高清'

    def _try_base64_decode(self, s: str) -> Optional[str]:
        """尝试 base64 解码"""
        try:
            # 补齐 padding
            padding = 4 - len(s) % 4
            if padding != 4:
                s += '=' * padding
            decoded = base64.b64decode(s).decode('utf-8')
            if self._is_valid_video_url(decoded):
                return decoded
        except Exception:
            pass
        return None

    def _deduplicate(self, sources: List[VideoSource]) -> List[VideoSource]:
        """去重"""
        seen = set()
        result = []
        for s in sources:
            if s.url not in seen:
                seen.add(s.url)
                result.append(s)
        return result

    def extract_to_tvbox_source(self, url: str, source_name: str = "") -> dict:
        """
        提取网页视频并转为 TVBox JSON 源格式

        返回可直接导入的 TVBox source dict:
        {
            "key": "web_extract",
            "name": "网页提取",
            "type": 1,
            "api": "csp_extract",  # 自定义解析
            "searchable": 0,
            "quickSearch": 0,
            "filterable": 0,
            "ext": { "url": "..." }
        }
        """
        sources = self.extract(url)
        if not sources:
            return {}

        # 取最高质量的源
        best = sources[0]

        name = source_name or urlparse(url).netloc

        return {
            "key": f"web_{hashlib.md5(url.encode()).hexdigest()[:8]}",
            "name": f"🌐 {name}",
            "type": 1,
            "api": "csp_extract",
            "searchable": 0,
            "quickSearch": 0,
            "filterable": 0,
            "ext": {
                "url": best.url,
                "type": best.source_type,
                "headers": best.headers,
                "page_url": url,
                "all_sources": [s.to_tvbox_source() for s in sources],
            }
        }


# ============================================================
#  快捷函数
# ============================================================

def extract_video_from_url(url: str) -> List[VideoSource]:
    """快捷函数: 从 URL 提取视频"""
    extractor = WebVideoExtractor()
    return extractor.extract(url)
