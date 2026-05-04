#!/usr/bin/env python3
"""TVBox Desktop — 元数据刮削器 (TMDB / 豆瓣 / 本地聚合)

用法:
    from core.scraper import MetadataScraper
    scraper = MetadataScraper()
    enriched = scraper.enrich(video_item)  # 自动填充海报、评分、简介等
"""

import re
import json
import hashlib
import os
import requests
from typing import Optional
from dataclasses import dataclass
from core.models import VideoItem

# ============================================================
#  缓存目录
# ============================================================
CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".cache", "metadata")
os.makedirs(CACHE_DIR, exist_ok=True)


def _cache_key(name: str, year: str = "") -> str:
    """生成缓存 key"""
    raw = f"{name.strip()}_{year.strip()}".lower()
    return hashlib.md5(raw.encode()).hexdigest()


def _get_cache(name: str, year: str = "") -> Optional[dict]:
    """读取本地缓存"""
    key = _cache_key(name, year)
    path = os.path.join(CACHE_DIR, f"{key}.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return None


def _set_cache(name: str, year: str, data: dict):
    """写入本地缓存"""
    key = _cache_key(name, year)
    path = os.path.join(CACHE_DIR, f"{key}.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ============================================================
#  刮削结果
# ============================================================
@dataclass
class MetadataResult:
    """刮削结果"""
    poster_url: str = ""        # 高清海报
    backdrop_url: str = ""      # 背景图
    rating: float = 0.0         # 评分
    overview: str = ""          # 简介
    genres: list = None         # 类型标签
    release_date: str = ""      # 上映日期
    tmdb_id: int = 0            # TMDB ID

    def __post_init__(self):
        if self.genres is None:
            self.genres = []


# ============================================================
#  TMDB 刮削 (需要 API Key, 可选)
# ============================================================
class TMDBScraper:
    """The Movie Database 刮削"""

    BASE_URL = "https://api.themoviedb.org/3"
    IMAGE_BASE = "https://image.tmdb.org/t/p"

    def __init__(self, api_key: str = ""):
        self.api_key = api_key or os.environ.get("TMDB_API_KEY", "")
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "TVBox Desktop/1.2"
        })

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def search(self, name: str, year: str = "", language: str = "zh-CN") -> Optional[MetadataResult]:
        """搜索影视元数据"""
        if not self.available:
            return None

        # 检查缓存
        cached = _get_cache(f"tmdb_{name}", year)
        if cached:
            return MetadataResult(**cached)

        try:
            params = {
                "api_key": self.api_key,
                "query": name,
                "language": language,
            }
            if year:
                params["year"] = year

            # 先搜电影
            result = self._search_type("movie", params, name, year)
            if result:
                return result

            # 再搜电视剧
            result = self._search_type("tv", params, name, year)
            return result

        except Exception as e:
            print(f"[TMDBScraper] 搜索失败: {e}")
            return None

    def _search_type(self, media_type: str, params: dict, name: str, year: str) -> Optional[MetadataResult]:
        """搜索指定类型"""
        resp = self.session.get(
            f"{self.BASE_URL}/search/{media_type}",
            params=params,
            timeout=10
        )
        resp.raise_for_status()
        data = resp.json()

        results = data.get("results", [])
        if not results:
            return None

        # 取最佳匹配
        best = results[0]

        poster_path = best.get("poster_path", "")
        backdrop_path = best.get("backdrop_path", "")

        result = MetadataResult(
            poster_url=f"{self.IMAGE_BASE}/w500{poster_path}" if poster_path else "",
            backdrop_url=f"{self.IMAGE_BASE}/original{backdrop_path}" if backdrop_path else "",
            rating=best.get("vote_average", 0.0),
            overview=best.get("overview", ""),
            release_date=best.get("release_date", "") or best.get("first_air_date", ""),
            tmdb_id=best.get("id", 0),
        )

        # 获取类型名称
        genre_ids = best.get("genre_ids", [])
        result.genres = self._get_genre_names(genre_ids, media_type)

        # 缓存
        _set_cache(f"tmdb_{name}", year, {
            "poster_url": result.poster_url,
            "backdrop_url": result.backdrop_url,
            "rating": result.rating,
            "overview": result.overview,
            "genres": result.genres,
            "release_date": result.release_date,
            "tmdb_id": result.tmdb_id,
        })

        return result

    def _get_genre_names(self, genre_ids: list, media_type: str) -> list:
        """获取类型名称"""
        try:
            resp = self.session.get(
                f"{self.BASE_URL}/genre/{media_type}/list",
                params={"api_key": self.api_key, "language": "zh-CN"},
                timeout=5
            )
            resp.raise_for_status()
            genres = resp.json().get("genres", [])
            id_map = {g["id"]: g["name"] for g in genres}
            return [id_map[gid] for gid in genre_ids if gid in id_map]
        except Exception:
            return []


# ============================================================
#  豆瓣刮削 (非官方, 仅供学习)
# ============================================================
class DoubanScraper:
    """豆瓣刮削 (通过搜索接口)"""

    SEARCH_URL = "https://movie.douban.com/j/subject_suggest"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://movie.douban.com/",
        })

    def search(self, name: str, year: str = "") -> Optional[MetadataResult]:
        """搜索豆瓣影视"""
        cached = _get_cache(f"douban_{name}", year)
        if cached:
            return MetadataResult(**cached)

        try:
            resp = self.session.get(
                self.SEARCH_URL,
                params={"q": name, "t": "movie"},
                timeout=10
            )
            resp.raise_for_status()
            results = resp.json()

            if not results:
                return None

            # 找最佳匹配
            best = None
            for r in results:
                if r.get("type") in ("movie", "tv"):
                    if year and r.get("year") == year:
                        best = r
                        break
                    if not best:
                        best = r

            if not best:
                return None

            result = MetadataResult(
                poster_url=best.get("img", ""),
                rating=float(best.get("rate", "0") or "0"),
                release_date=best.get("year", ""),
            )

            _set_cache(f"douban_{name}", year, {
                "poster_url": result.poster_url,
                "backdrop_url": result.backdrop_url,
                "rating": result.rating,
                "overview": result.overview,
                "genres": result.genres,
                "release_date": result.release_date,
                "tmdb_id": result.tmdb_id,
            })

            return result

        except Exception as e:
            print(f"[DoubanScraper] 搜索失败: {e}")
            return None


# ============================================================
#  聚合刮削器
# ============================================================
class MetadataScraper:
    """聚合元数据刮削器 — 按优先级尝试多个源"""

    def __init__(self, tmdb_api_key: str = ""):
        self.tmdb = TMDBScraper(tmdb_api_key)
        self.douban = DoubanScraper()

    def enrich(self, video: VideoItem) -> VideoItem:
        """
        刮削并填充 VideoItem 的缺失元数据
        - 如果已有 pic 则保留原图（源自带的封面优先）
        - 补充 rating、description、genres 等
        """
        # 如果已有完整信息，跳过
        if video.pic and video.description and video.year:
            return video

        name = video.name.strip()
        year = video.year.strip() if video.year else ""

        # 清理名称中的多余信息（如 "电影名 2024" → "电影名"）
        clean_name = re.sub(r'\s*\d{4}\s*$', '', name).strip()

        result = None

        # 1. 优先 TMDB (质量最好)
        if self.tmdb.available:
            result = self.tmdb.search(clean_name, year)

        # 2. 回退到豆瓣
        if not result:
            result = self.douban.search(clean_name, year)

        if not result:
            return video

        # 填充缺失字段
        if not video.pic and result.poster_url:
            video.pic = result.poster_url
        if not video.description and result.overview:
            video.description = result.overview
        if not video.year and result.release_date:
            video.year = result.release_date[:4] if len(result.release_date) >= 4 else result.release_date
        if result.genres and not video.type_name:
            video.type_name = " / ".join(result.genres)

        return video

    def enrich_batch(self, videos: list, max_workers: int = 4) -> list:
        """批量刮削（限流，避免被封）"""
        import time
        enriched = []
        for i, v in enumerate(videos):
            enriched.append(self.enrich(v))
            # 每处理 5 个暂停一下，避免请求过快
            if i > 0 and i % 5 == 0:
                time.sleep(0.5)
        return enriched
