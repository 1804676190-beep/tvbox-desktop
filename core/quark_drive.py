#!/usr/bin/env python3
"""TVBox Desktop — 夸克网盘客户端

支持:
  - 扫码登录 (QR Code OAuth)
  - 文件列表浏览
  - 视频直链获取 (302 重定向)
  - 自动刷新 token

API 文档: 非官方逆向, 参考 alist/quark 项目
"""

import os
import json
import time
import uuid
import hashlib
import requests
from typing import List, Optional, Dict
from dataclasses import dataclass, field
from urllib.parse import quote

# ============================================================
#  常量
# ============================================================
QUARK_API = "https://drive-pc.quark.cn/1/clouddrive"
QUARK_AUTH_URL = "https://member.quark.cn/1/page/h5"
QUARK_REFERER = "https://pan.quark.cn/"

# Token 持久化
TOKEN_FILE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    ".cache", "quark_token.json"
)


@dataclass
class QuarkFile:
    """夸克网盘文件"""
    file_id: str
    name: str
    path: str
    is_dir: bool = False
    size: int = 0
    modified_at: str = ""
    thumbnail: str = ""
    category: int = 0  # 0=其他, 1=视频, 2=音频, 3=图片, 4=文档
    format_type: str = ""

    @property
    def ext(self) -> str:
        if '.' in self.name:
            return '.' + self.name.rsplit('.', 1)[1].lower()
        return ''

    @property
    def is_video(self) -> bool:
        video_exts = {
            '.mp4', '.mkv', '.avi', '.flv', '.ts', '.m3u8', '.rmvb',
            '.wmv', '.mov', '.mpg', '.mpeg', '.3gp', '.webm', '.vob',
            '.f4v', '.m4v'
        }
        return self.ext in video_exts or self.category == 1

    @property
    def size_str(self) -> str:
        if self.size < 1024:
            return f"{self.size} B"
        elif self.size < 1024 * 1024:
            return f"{self.size / 1024:.1f} KB"
        elif self.size < 1024 * 1024 * 1024:
            return f"{self.size / (1024 * 1024):.1f} MB"
        else:
            return f"{self.size / (1024 * 1024 * 1024):.2f} GB"


@dataclass
class QRCodeSession:
    """扫码登录会话"""
    qrcode_id: str = ""
    qrcode_url: str = ""      # 二维码内容 URL
    status: str = "pending"    # pending / scanned / confirmed / expired
    cookie_token: str = ""     # 登录成功后的 cookie token


class QuarkDriveClient:
    """夸克网盘客户端"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": QUARK_REFERER,
            "Accept": "application/json, text/plain, */*",
        })

        self._token = ""
        self._cookie = ""
        self._folder_token = ""  # 根目录 token
        self._nickname = ""

        # 尝试加载已保存的 token
        self._load_token()

    # ============================================================
    #  扫码登录
    # ============================================================

    def request_qrcode(self) -> QRCodeSession:
        """
        请求扫码登录二维码

        返回 QRCodeSession, 包含二维码 URL
        前端/调用方需要:
          1. 用 qrcode_url 生成二维码图片展示给用户
          2. 轮询 check_qr_status() 直到确认或超时
        """
        session = QRCodeSession()

        try:
            # 生成唯一 ID
            qr_id = str(uuid.uuid4()).replace("-", "")[:32]
            timestamp = str(int(time.time() * 1000))

            # 请求二维码
            resp = self.session.get(
                f"{QUARK_AUTH_URL}/login/query",
                params={
                    "client_id": "575",
                    "v": timestamp,
                    "request_id": qr_id,
                },
                timeout=10
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("code") == 0 or data.get("status") == 200:
                qr_data = data.get("data", {})
                session.qrcode_id = qr_data.get("qrcode_id", qr_id)
                session.qrcode_url = qr_data.get("qrcode_url",
                    f"https://su.quark.cn/{qr_id}")
                session.status = "pending"
            else:
                # 备用方案: 使用固定格式生成
                session.qrcode_id = qr_id
                session.qrcode_url = f"https://su.quark.cn/{qr_id}"
                session.status = "pending"

        except Exception as e:
            print(f"[QuarkDrive] 请求二维码失败: {e}")
            # 降级方案
            session.qrcode_id = str(uuid.uuid4())[:16]
            session.qrcode_url = f"https://su.quark.cn/{session.qrcode_id}"

        return session

    def check_qr_status(self, session: QRCodeSession) -> QRCodeSession:
        """
        检查二维码扫描状态

        返回更新后的 session, 检查 session.status:
          - "pending": 等待扫描
          - "scanned": 已扫描, 等待确认
          - "confirmed": 已确认, 登录成功
          - "expired": 已过期
        """
        try:
            timestamp = str(int(time.time() * 1000))
            resp = self.session.get(
                f"{QUARK_AUTH_URL}/login/query",
                params={
                    "client_id": "575",
                    "qrcode_id": session.qrcode_id,
                    "v": timestamp,
                },
                timeout=10
            )
            resp.raise_for_status()
            data = resp.json()

            status_code = data.get("data", {}).get("status", 0)

            if status_code == 0:
                session.status = "pending"
            elif status_code == 1:
                session.status = "scanned"
            elif status_code == 2:
                # 登录成功, 获取 token
                session.status = "confirmed"
                login_data = data.get("data", {})
                self._token = login_data.get("access_token", "")
                self._cookie = login_data.get("cookie", "")
                self._nickname = login_data.get("nickname", "")

                # 保存 token
                self._save_token()

            elif status_code == 3:
                session.status = "expired"

        except Exception as e:
            print(f"[QuarkDrive] 检查二维码状态失败: {e}")

        return session

    # ============================================================
    #  Token 管理
    # ============================================================

    def _save_token(self):
        """保存 token 到本地"""
        os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
        data = {
            "token": self._token,
            "cookie": self._cookie,
            "nickname": self._nickname,
            "saved_at": time.time(),
        }
        try:
            with open(TOKEN_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[QuarkDrive] 保存 token 失败: {e}")

    def _load_token(self):
        """从本地加载 token"""
        if not os.path.exists(TOKEN_FILE):
            return
        try:
            with open(TOKEN_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._token = data.get("token", "")
            self._cookie = data.get("cookie", "")
            self._nickname = data.get("nickname", "")
            if self._token:
                self.session.headers["cookie"] = self._cookie
        except Exception as e:
            print(f"[QuarkDrive] 加载 token 失败: {e}")

    def is_logged_in(self) -> bool:
        """检查是否已登录"""
        return bool(self._token)

    def get_nickname(self) -> str:
        """获取用户昵称"""
        return self._nickname

    def logout(self):
        """登出"""
        self._token = ""
        self._cookie = ""
        self._nickname = ""
        if os.path.exists(TOKEN_FILE):
            os.remove(TOKEN_FILE)

    def _get_headers(self) -> dict:
        """获取带认证的请求头"""
        headers = {
            "Referer": QUARK_REFERER,
        }
        if self._token:
            headers["cookie"] = self._cookie
        return headers

    # ============================================================
    #  文件操作
    # ============================================================

    def list_dir(self, parent_fid: str = "0", page: int = 1, size: int = 100) -> List[QuarkFile]:
        """
        列出目录下的文件

        参数:
            parent_fid: 父目录 fid, "0" 为根目录
            page: 页码
            size: 每页数量

        返回:
            文件列表
        """
        files = []
        if not self.is_logged_in():
            print("[QuarkDrive] 未登录")
            return files

        try:
            resp = self.session.get(
                f"{QUARK_API}/file/sort",
                params={
                    "pdir_fid": parent_fid,
                    "_page": page,
                    "_size": size,
                    "_fetch_total": 1,
                    "_sort": "file_type:asc,updated_at:desc",
                },
                headers=self._get_headers(),
                timeout=15
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("code") == 0 or data.get("status") == 200:
                for item in data.get("data", {}).get("list", []):
                    f = QuarkFile(
                        file_id=item.get("fid", ""),
                        name=item.get("file_name", ""),
                        path=f"/{item.get('file_name', '')}",
                        is_dir=item.get("dir", False),
                        size=item.get("size", 0),
                        modified_at=item.get("updated_at", ""),
                        thumbnail=item.get("thumbnail", {}).get("url", "") if isinstance(item.get("thumbnail"), dict) else "",
                        category=item.get("category", 0),
                        format_type=item.get("format_type", ""),
                    )
                    files.append(f)

        except Exception as e:
            print(f"[QuarkDrive] 列目录失败: {e}")

        return files

    def get_file_info(self, fid: str) -> Optional[QuarkFile]:
        """获取文件详情"""
        if not self.is_logged_in():
            return None

        try:
            resp = self.session.get(
                f"{QUARK_API}/file/sort",
                params={
                    "fids": fid,
                    "_page": 1,
                    "_size": 1,
                },
                headers=self._get_headers(),
                timeout=10
            )
            resp.raise_for_status()
            data = resp.json()

            items = data.get("data", {}).get("list", [])
            if items:
                item = items[0]
                return QuarkFile(
                    file_id=item.get("fid", ""),
                    name=item.get("file_name", ""),
                    path=f"/{item.get('file_name', '')}",
                    is_dir=item.get("dir", False),
                    size=item.get("size", 0),
                    modified_at=item.get("updated_at", ""),
                    category=item.get("category", 0),
                )
        except Exception as e:
            print(f"[QuarkDrive] 获取文件信息失败: {e}")

        return None

    def get_video_play_url(self, fid: str) -> Optional[str]:
        """
        获取视频播放直链

        返回 302 重定向后的直链, 可直接传给 mpv 播放
        """
        if not self.is_logged_in():
            return None

        try:
            # 调用播放接口
            resp = self.session.post(
                f"{QUARK_API}/file/v2/play",
                json={
                    "fid": fid,
                    "resolutions": "normal,low,high,super,2k,4k",
                    "supports": "fmp4",
                },
                headers=self._get_headers(),
                timeout=15
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("code") == 0 or data.get("status") == 200:
                video_list = data.get("data", {}).get("video_list", [])
                if video_list:
                    # 取最高画质
                    best = video_list[-1]
                    play_url = best.get("url", "")
                    if play_url:
                        return play_url

        except Exception as e:
            print(f"[QuarkDrive] 获取播放链接失败: {e}")

        return None

    def search_files(self, keyword: str, page: int = 1, size: int = 50) -> List[QuarkFile]:
        """搜索文件"""
        files = []
        if not self.is_logged_in():
            return files

        try:
            resp = self.session.get(
                f"{QUARK_API}/file/search",
                params={
                    "key": keyword,
                    "_page": page,
                    "_size": size,
                    "_is_hl": 1,
                },
                headers=self._get_headers(),
                timeout=15
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("code") == 0 or data.get("status") == 200:
                for item in data.get("data", {}).get("list", []):
                    f = QuarkFile(
                        file_id=item.get("fid", ""),
                        name=item.get("file_name", ""),
                        path=f"/{item.get('file_name', '')}",
                        is_dir=item.get("dir", False),
                        size=item.get("size", 0),
                        modified_at=item.get("updated_at", ""),
                        category=item.get("category", 0),
                    )
                    files.append(f)

        except Exception as e:
            print(f"[QuarkDrive] 搜索失败: {e}")

        return files

    # ============================================================
    #  TVBox 集成
    # ============================================================

    def get_quota(self) -> dict:
        """获取网盘容量信息"""
        if not self.is_logged_in():
            return {}

        try:
            resp = self.session.get(
                f"{QUARK_API}/capacity",
                headers=self._get_headers(),
                timeout=10
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("code") == 0 or data.get("status") == 200:
                cap = data.get("data", {})
                return {
                    "total": cap.get("total_capacity", 0),
                    "used": cap.get("use_capacity", 0),
                    "total_str": self._format_size(cap.get("total_capacity", 0)),
                    "used_str": self._format_size(cap.get("use_capacity", 0)),
                }
        except Exception as e:
            print(f"[QuarkDrive] 获取容量失败: {e}")

        return {}

    @staticmethod
    def _format_size(size: int) -> str:
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        elif size < 1024 * 1024 * 1024:
            return f"{size / (1024 * 1024):.1f} MB"
        else:
            return f"{size / (1024 * 1024 * 1024):.2f} GB"

    def to_tvbox_source(self, fid: str = "0", name: str = "夸克网盘") -> dict:
        """
        将夸克网盘目录转为 TVBox 源格式

        返回:
            TVBox JSON 中的一个 site 条目
        """
        return {
            "key": f"quark_{fid}",
            "name": f"☁️ {name}",
            "type": 3,
            "api": "csp_quark",
            "searchable": 0,
            "quickSearch": 0,
            "filterable": 0,
            "ext": {
                "fid": fid,
                "drive_type": "quark",
            }
        }
