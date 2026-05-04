#!/usr/bin/env python3
"""TVBox Desktop — 网盘客户端 (Alist / WebDAV)"""

import requests
from dataclasses import dataclass
from typing import List, Optional
from urllib.parse import quote, urljoin


@dataclass
class CloudFile:
    """网盘文件"""
    name: str
    path: str
    is_dir: bool = False
    size: int = 0
    modified: str = ""
    thumb: str = ""
    provider: str = ""
    raw_url: str = ""

    @property
    def ext(self) -> str:
        """文件扩展名（小写）"""
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
        return self.ext in video_exts

    @property
    def is_media(self) -> bool:
        media_exts = {
            '.mp4', '.mkv', '.avi', '.flv', '.ts', '.m3u8', '.rmvb',
            '.wmv', '.mov', '.mpg', '.mpeg', '.3gp', '.webm', '.vob',
            '.f4v', '.m4v', '.mp3', '.wav', '.flac', '.aac', '.ogg',
            '.wma', '.m4a'
        }
        return self.ext in media_exts

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


class AlistClient:
    """Alist API 客户端"""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip('/')
        self.token = ""
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'TVBox Desktop'
        })

    def login(self, username: str, password: str) -> bool:
        """登录获取 token"""
        try:
            resp = self.session.post(
                f"{self.base_url}/api/auth/login",
                json={"username": username, "password": password},
                timeout=10
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get('code') == 200:
                self.token = data.get('data', {}).get('token', '')
                self.session.headers['Authorization'] = self.token
                return True
            return False
        except Exception as e:
            print(f"[AlistClient] 登录失败: {e}")
            return False

    def set_token(self, token: str):
        """直接设置 token"""
        self.token = token
        self.session.headers['Authorization'] = token

    def list_dir(self, path: str = "/") -> List[CloudFile]:
        """列出目录"""
        files = []
        try:
            resp = self.session.post(
                f"{self.base_url}/api/fs/list",
                json={"path": path, "per_page": 0, "refresh": False},
                timeout=15
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get('code') == 200:
                for item in data.get('data', {}).get('content', []):
                    f = CloudFile(
                        name=item.get('name', ''),
                        path=f"{path.rstrip('/')}/{item.get('name', '')}",
                        is_dir=item.get('is_dir', False),
                        size=item.get('size', 0),
                        modified=item.get('modified', ''),
                        thumb=item.get('thumb', ''),
                        provider=item.get('provider', ''),
                    )
                    files.append(f)
        except Exception as e:
            print(f"[AlistClient] 列目录失败: {e}")
        return files

    def get_file_info(self, path: str) -> Optional[CloudFile]:
        """获取文件信息"""
        try:
            resp = self.session.post(
                f"{self.base_url}/api/fs/get",
                json={"path": path},
                timeout=10
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get('code') == 200:
                item = data.get('data', {})
                return CloudFile(
                    name=item.get('name', path.split('/')[-1]),
                    path=path,
                    is_dir=False,
                    size=item.get('size', 0),
                    modified=item.get('modified', ''),
                    raw_url=item.get('raw_url', ''),
                )
        except Exception as e:
            print(f"[AlistClient] 获取文件信息失败: {e}")
        return None

    def get_download_url(self, path: str) -> str:
        """获取播放直链"""
        try:
            resp = self.session.post(
                f"{self.base_url}/api/fs/get",
                json={"path": path},
                timeout=10
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get('code') == 200:
                raw_url = data.get('data', {}).get('raw_url', '')
                if raw_url:
                    return raw_url
        except Exception:
            pass
        # fallback: 拼接下载链接
        encoded = quote(path, safe='/')
        return f"{self.base_url}/d{encoded}"

    def search(self, keyword: str, path: str = "/", scope: str = "0") -> List[CloudFile]:
        """搜索文件"""
        files = []
        try:
            resp = self.session.post(
                f"{self.base_url}/api/fs/search",
                json={
                    "parent": path,
                    "keywords": keyword,
                    "scope": scope,
                    "per_page": 100
                },
                timeout=15
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get('code') == 200:
                for item in data.get('data', {}).get('content', []):
                    f = CloudFile(
                        name=item.get('name', ''),
                        path=item.get('path', ''),
                        is_dir=item.get('is_dir', False),
                        size=item.get('size', 0),
                    )
                    files.append(f)
        except Exception as e:
            print(f"[AlistClient] 搜索失败: {e}")
        return files


class WebDAVClient:
    """WebDAV 客户端"""

    def __init__(self, base_url: str, username: str = "", password: str = ""):
        self.base_url = base_url.rstrip('/')
        self.auth = (username, password) if username else None

    def list_dir(self, path: str = "/") -> List[CloudFile]:
        """PROPFIND 列目录"""
        files = []
        try:
            url = f"{self.base_url}{path}"
            if not url.endswith('/'):
                url += '/'
            headers = {
                'Depth': '1',
                'Content-Type': 'application/xml',
            }
            body = '<?xml version="1.0"?><propfind xmlns="DAV:"><allprop/></propfind>'
            resp = requests.request(
                'PROPFIND', url,
                headers=headers, data=body,
                auth=self.auth, timeout=15
            )
            if resp.status_code not in (207, 200):
                print(f"[WebDAVClient] PROPFIND 失败: {resp.status_code}")
                return files

            from bs4 import BeautifulSoup
            soup = BeautifulSoup(resp.text, 'lxml-xml')

            for response in soup.find_all('d:response') or soup.find_all('response'):
                href_tag = response.find('d:href') or response.find('href')
                if not href_tag:
                    continue
                href = href_tag.text.strip()

                res_type = response.find('d:resourcetype') or response.find('resourcetype')
                is_dir = False
                if res_type:
                    is_dir = res_type.find('d:collection') is not None or res_type.find('collection') is not None

                name = href.rstrip('/').split('/')[-1]
                if not name:
                    continue

                # 获取文件大小
                size = 0
                size_tag = response.find('d:getcontentlength') or response.find('getcontentlength')
                if size_tag and size_tag.text:
                    try:
                        size = int(size_tag.text)
                    except ValueError:
                        pass

                f = CloudFile(
                    name=name,
                    path=href,
                    is_dir=is_dir,
                    size=size,
                )
                files.append(f)

        except Exception as e:
            print(f"[WebDAVClient] 列目录失败: {e}")
        return files

    def get_download_url(self, path: str) -> str:
        """获取完整下载 URL"""
        return f"{self.base_url}{path}"
