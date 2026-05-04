#!/usr/bin/env python3
"""TVBox Desktop — 数据模型"""

import json
import os
from dataclasses import dataclass, field, asdict
from typing import List


CONFIG_FILE = "tvbox_state.json"


@dataclass
class VideoItem:
    """视频条目"""
    name: str
    url: str = ""
    pic: str = ""
    group: str = ""
    description: str = ""
    year: str = ""
    area: str = ""
    type_name: str = ""
    director: str = ""
    actor: str = ""
    episodes: list = field(default_factory=list)       # [{name, url}]
    play_sources: list = field(default_factory=list)   # [{name: str, episodes: [{name, url}]}]

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class LiveChannel:
    """直播频道"""
    name: str
    urls: list = field(default_factory=list)
    group: str = ""

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class SourceInfo:
    """订阅源"""
    name: str
    url: str
    source_type: str = "json"   # json / xml
    enabled: bool = True
    last_update: str = ""
    repo_name: str = ""

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class Repository:
    """仓库"""
    name: str
    url: str
    enabled: bool = True
    last_update: str = ""
    source_count: int = 0

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class CloudDriveConfig:
    """网盘配置"""
    name: str
    drive_type: str = "alist"   # alist / webdav
    url: str = ""
    username: str = ""
    password: str = ""
    token: str = ""
    enabled: bool = True

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class Category:
    """分类"""
    name: str
    type_id: str = ""
    items: list = field(default_factory=list)  # list[VideoItem]

    def to_dict(self):
        d = asdict(self)
        d['items'] = [i.to_dict() if hasattr(i, 'to_dict') else i for i in self.items]
        return d

    @classmethod
    def from_dict(cls, d):
        items = [VideoItem.from_dict(i) if isinstance(i, dict) else i for i in d.get('items', [])]
        return cls(name=d.get('name', ''), type_id=d.get('type_id', ''), items=items)


@dataclass
class AppState:
    """应用状态（持久化）"""
    sources: List[SourceInfo] = field(default_factory=list)
    repositories: List[Repository] = field(default_factory=list)
    cloud_drives: List[CloudDriveConfig] = field(default_factory=list)
    favorites: List[VideoItem] = field(default_factory=list)
    history: List[VideoItem] = field(default_factory=list)
    last_source_index: int = 0

    def save(self):
        data = {
            'sources': [s.to_dict() for s in self.sources],
            'repositories': [r.to_dict() for r in self.repositories],
            'cloud_drives': [c.to_dict() for c in self.cloud_drives],
            'favorites': [f.to_dict() for f in self.favorites],
            'history': [h.to_dict() for h in self.history],
            'last_source_index': self.last_source_index,
        }
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[AppState] 保存失败: {e}")

    @classmethod
    def load(cls) -> 'AppState':
        if not os.path.exists(CONFIG_FILE):
            return cls()
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            state = cls()
            state.sources = [SourceInfo.from_dict(s) for s in data.get('sources', [])]
            state.repositories = [Repository.from_dict(r) for r in data.get('repositories', [])]
            state.cloud_drives = [CloudDriveConfig.from_dict(c) for c in data.get('cloud_drives', [])]
            state.favorites = [VideoItem.from_dict(v) for v in data.get('favorites', [])]
            state.history = [VideoItem.from_dict(v) for v in data.get('history', [])]
            state.last_source_index = data.get('last_source_index', 0)
            return state
        except Exception as e:
            print(f"[AppState] 加载失败: {e}")
            return cls()

    def add_history(self, video: VideoItem, max_items: int = 100):
        """添加到观看历史（去重，最新的在前）"""
        self.history = [v for v in self.history if v.url != video.url]
        self.history.insert(0, video)
        if len(self.history) > max_items:
            self.history = self.history[:max_items]
        self.save()

    def toggle_favorite(self, video: VideoItem) -> bool:
        """切换收藏状态，返回是否已收藏"""
        for i, fav in enumerate(self.favorites):
            if fav.url == video.url:
                self.favorites.pop(i)
                self.save()
                return False
        self.favorites.insert(0, video)
        self.save()
        return True

    def is_favorite(self, video: VideoItem) -> bool:
        return any(f.url == video.url for f in self.favorites)
