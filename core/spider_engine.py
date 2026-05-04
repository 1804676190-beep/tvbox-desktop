#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TVBox Desktop — JS Spider 执行引擎

支持 type 3 站点，通过执行 JS Spider 文件获取数据。
当 JS 执行失败时，自动降级为直接 CMS API 调用（type 0 模式）。

用法:
    from core.spider_engine import SpiderEngine
    engine = SpiderEngine()
    # 解析订阅源后，对 type 3 站点调用:
    result = engine.homeContent(api_url, filter=True)
    result = engine.category(api_url, tid="1", pg=1)
    result = engine.detail(api_url, ids="123")
    result = engine.search(api_url, keyword="测试")
    result = engine.play(api_url, flag="播放源", id="播放地址")
"""

import os
import re
import json
import hashlib
import time
import subprocess
import tempfile
from typing import Optional, Dict, Any, List, Tuple
from urllib.parse import urljoin, urlparse, urlencode, quote

import requests

# ============================================================
#  常量与路径
# ============================================================
CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".cache", "spider")
os.makedirs(CACHE_DIR, exist_ok=True)

# Node.js 执行超时（秒）
JS_EXEC_TIMEOUT = 30

# 请求超时（秒）
HTTP_TIMEOUT = 15

# User-Agent
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


# ============================================================
#  JS 执行器模板
# ============================================================
# 该模板在 Node.js 环境中运行，加载 spider JS 文件并调用指定方法
JS_RUNNER_TEMPLATE = r"""
'use strict';

// ===== Polyfill: 模拟 Android/TVBox 的 Java 环境 =====
const _httpResponses = {};
const _cookieJar = {};

// 模拟 OkHttpClient（简化版，通过 fetch/http 实现）
globalThis.okhttp = {
    newCall: function(request) {
        return {
            execute: function() {
                // 由 Python 端注入实际的 HTTP 结果
                return { body: function() { return { string: function() { return '{}'; } }; } };
            }
        };
    }
};

// 模拟 jsoup（简化版）
globalThis.jsoup = {
    connect: function(url) {
        return {
            get: function() { return null; },
            post: function() { return null; }
        };
    }
};

// Spider 需要的标准对象
globalThis.log = function() {
    // 将日志输出到 stderr，不干扰 stdout 的 JSON 结果
    console.error('[Spider]', Array.from(arguments).join(' '));
};

globalThis.print = function() {
    console.error('[Spider]', Array.from(arguments).join(' '));
};

// ===== 加载 Spider 文件 =====
try {
    %SPIDER_CODE%
} catch(e) {
    console.error('[SpiderLoader] 加载 Spider 失败:', e.message);
    process.exit(1);
}

// ===== 执行请求 =====
const args = JSON.parse(process.argv[2] || '{}');
const method = args.method || 'homeContent';
const params = args.params || {};

async function runSpider() {
    try {
        // 查找 Spider 类实例
        // TVBox spider 通常通过 globalThis 导出，类名格式为 csp_XXX
        let spider = null;

        // 方式1: 直接在 globalThis 上查找
        const className = args.className || '';
        if (className && globalThis[className]) {
            spider = typeof globalThis[className] === 'function'
                ? new globalThis[className]()
                : globalThis[className];
        }

        // 方式2: 查找所有 globalThis 上的对象，找到有目标方法的
        if (!spider) {
            for (const key of Object.keys(globalThis)) {
                const obj = globalThis[key];
                if (obj && typeof obj === 'object' && typeof obj[method] === 'function') {
                    spider = obj;
                    break;
                }
                if (typeof obj === 'function') {
                    try {
                        const instance = new obj();
                        if (instance && typeof instance[method] === 'function') {
                            spider = instance;
                            break;
                        }
                    } catch(e) { /* 不是构造函数，跳过 */ }
                }
            }
        }

        // 方式3: 尝试查找 Spider 变量名
        if (!spider && globalThis.Spider) {
            spider = typeof globalThis.Spider === 'function'
                ? new globalThis.Spider()
                : globalThis.Spider;
        }

        if (!spider) {
            console.error('[SpiderLoader] 未找到 Spider 实例');
            process.stdout.write(JSON.stringify({error: '未找到 Spider 实例'}));
            process.exit(0);
        }

        if (typeof spider[method] !== 'function') {
            console.error('[SpiderLoader] Spider 不支持方法:', method);
            process.stdout.write(JSON.stringify({error: '不支持的方法: ' + method}));
            process.exit(0);
        }

        // 调用方法
        let result;
        switch(method) {
            case 'homeContent':
                result = await spider.homeContent(params.filter !== false);
                break;
            case 'homeVod':
                result = await spider.homeVod();
                break;
            case 'category':
                result = await spider.category(params.tid, params.pg || 1, params.filter !== false, params.extend || {});
                break;
            case 'detail':
                result = await spider.detail(params.ids || params.id);
                break;
            case 'play':
                result = await spider.play(params.flag, params.id, params.flags || []);
                break;
            case 'search':
                result = await spider.search(params.wd || params.keyword, params.quick !== false);
                break;
            default:
                result = {error: '未知方法: ' + method};
        }

        // 输出 JSON 结果到 stdout
        const output = JSON.stringify(result || {});
        process.stdout.write(output);
    } catch(e) {
        console.error('[SpiderLoader] 执行失败:', e.message, e.stack);
        process.stdout.write(JSON.stringify({error: e.message}));
    }
}

runSpider();
"""


# ============================================================
#  HTTP 请求工具
# ============================================================
class HttpHelper:
    """HTTP 请求工具类，提供统一的请求接口"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': USER_AGENT,
            'Accept': '*/*',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        })
        self.session.verify = False
        # 禁用 SSL 警告
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def get(self, url: str, params: dict = None, headers: dict = None,
            timeout: int = HTTP_TIMEOUT) -> Optional[str]:
        """GET 请求，返回响应文本"""
        try:
            resp = self.session.get(url, params=params, headers=headers, timeout=timeout)
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding or 'utf-8'
            return resp.text
        except Exception as e:
            print(f"[HttpHelper] GET 请求失败 {url}: {e}")
            return None

    def get_json(self, url: str, params: dict = None, headers: dict = None,
                 timeout: int = HTTP_TIMEOUT) -> Optional[dict]:
        """GET 请求，返回 JSON"""
        text = self.get(url, params, headers, timeout)
        if text is None:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            print(f"[HttpHelper] JSON 解析失败 {url}: {e}")
            return None

    def post_json(self, url: str, data: dict = None, json_data: dict = None,
                  headers: dict = None, timeout: int = HTTP_TIMEOUT) -> Optional[dict]:
        """POST 请求，返回 JSON"""
        try:
            resp = self.session.post(url, data=data, json=json_data,
                                     headers=headers, timeout=timeout)
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding or 'utf-8'
            return resp.json()
        except Exception as e:
            print(f"[HttpHelper] POST 请求失败 {url}: {e}")
            return None


# ============================================================
#  Spider 文件缓存管理
# ============================================================
class SpiderCache:
    """Spider 文件缓存管理器

    缓存目录结构:
        .cache/spider/
            ├── {md5_hash}.js          # spider 文件
            └── {md5_hash}.meta.json   # 元数据（URL、下载时间等）
    """

    def __init__(self, cache_dir: str = CACHE_DIR):
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)

    def get_cache_path(self, url: str) -> str:
        """根据 URL 生成缓存文件路径"""
        url_hash = hashlib.md5(url.encode('utf-8')).hexdigest()
        return os.path.join(self.cache_dir, f"{url_hash}.js")

    def get_meta_path(self, url: str) -> str:
        """获取元数据文件路径"""
        url_hash = hashlib.md5(url.encode('utf-8')).hexdigest()
        return os.path.join(self.cache_dir, f"{url_hash}.meta.json")

    def is_cached(self, url: str) -> bool:
        """检查是否已缓存"""
        cache_path = self.get_cache_path(url)
        meta_path = self.get_meta_path(url)
        return os.path.exists(cache_path) and os.path.exists(meta_path)

    def get_cached_content(self, url: str) -> Optional[str]:
        """读取缓存的 spider 文件内容"""
        if not self.is_cached(url):
            return None

        cache_path = self.get_cache_path(url)
        meta_path = self.get_meta_path(url)

        try:
            # 读取元数据
            with open(meta_path, 'r', encoding='utf-8') as f:
                meta = json.load(f)

            # 读取文件内容
            with open(cache_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # MD5 校验
            expected_md5 = meta.get('md5', '')
            if expected_md5:
                actual_md5 = hashlib.md5(content.encode('utf-8')).hexdigest()
                if actual_md5 != expected_md5:
                    print(f"[SpiderCache] MD5 校验失败，缓存无效: {url}")
                    self.remove(url)
                    return None

            print(f"[SpiderCache] 使用缓存: {url}")
            return content
        except Exception as e:
            print(f"[SpiderCache] 读取缓存失败: {e}")
            return None

    def save(self, url: str, content: str):
        """保存 spider 文件到缓存"""
        cache_path = self.get_cache_path(url)
        meta_path = self.get_meta_path(url)

        try:
            # 计算 MD5
            md5_hash = hashlib.md5(content.encode('utf-8')).hexdigest()

            # 写入文件
            with open(cache_path, 'w', encoding='utf-8') as f:
                f.write(content)

            # 写入元数据
            meta = {
                'url': url,
                'md5': md5_hash,
                'size': len(content),
                'cached_at': time.time(),
                'cached_date': time.strftime('%Y-%m-%d %H:%M:%S'),
            }
            with open(meta_path, 'w', encoding='utf-8') as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)

            print(f"[SpiderCache] 已缓存 spider: {url} ({len(content)} bytes)")
        except Exception as e:
            print(f"[SpiderCache] 保存缓存失败: {e}")

    def remove(self, url: str):
        """删除指定 URL 的缓存"""
        cache_path = self.get_cache_path(url)
        meta_path = self.get_meta_path(url)
        for path in (cache_path, meta_path):
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass

    def clear_all(self):
        """清空所有缓存"""
        import glob
        for f in glob.glob(os.path.join(self.cache_dir, "*.js")) + \
                 glob.glob(os.path.join(self.cache_dir, "*.meta.json")):
            try:
                os.remove(f)
            except OSError:
                pass
        print("[SpiderCache] 已清空所有缓存")


# ============================================================
#  JS Spider 执行器
# ============================================================
class JSExecutor:
    """通过 Node.js 子进程执行 JS Spider"""

    def __init__(self, timeout: int = JS_EXEC_TIMEOUT):
        self.timeout = timeout
        self._node_available = self._check_node()

    def _check_node(self) -> bool:
        """检查 Node.js 是否可用"""
        try:
            result = subprocess.run(
                ['node', '--version'],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                version = result.stdout.strip()
                print(f"[JSExecutor] Node.js 可用: {version}")
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        print("[JSExecutor] Node.js 不可用，JS Spider 将无法执行")
        return False

    @property
    def available(self) -> bool:
        """Node.js 是否可用"""
        return self._node_available

    def execute(self, spider_code: str, method: str, params: dict = None,
                class_name: str = None) -> Optional[dict]:
        """执行 JS Spider 的指定方法

        Args:
            spider_code: Spider JS 文件内容
            method: 要调用的方法名 (homeContent, category, detail, play, search 等)
            params: 方法参数
            class_name: Spider 类名（如 csp_XXX）

        Returns:
            解析后的 JSON 结果，失败返回 None
        """
        if not self._node_available:
            print("[JSExecutor] Node.js 不可用，无法执行 Spider")
            return None

        # 构建执行参数
        exec_args = {
            'method': method,
            'params': params or {},
            'className': class_name or '',
        }

        # 生成完整的 JS 代码
        full_code = JS_RUNNER_TEMPLATE.replace('%SPIDER_CODE%', spider_code)

        # 写入临时文件执行（避免命令行参数过长）
        tmp_file = None
        try:
            fd, tmp_file = tempfile.mkstemp(suffix='.cjs', prefix='tvbox_spider_')
            os.close(fd)

            with open(tmp_file, 'w', encoding='utf-8') as f:
                f.write(full_code)

            # 执行 Node.js
            result = subprocess.run(
                ['node', tmp_file, json.dumps(exec_args, ensure_ascii=False)],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env={**os.environ, 'NODE_NO_WARNINGS': '1'}
            )

            # 解析 stdout 中的 JSON 结果
            stdout = result.stdout.strip()
            stderr = result.stderr.strip()

            # 输出调试信息（stderr 中的日志）
            if stderr:
                for line in stderr.split('\n'):
                    if line.strip():
                        print(f"  {line}")

            if not stdout:
                print("[JSExecutor] Spider 无输出")
                return None

            try:
                data = json.loads(stdout)
                if isinstance(data, dict) and 'error' in data and len(data) == 1:
                    print(f"[JSExecutor] Spider 返回错误: {data['error']}")
                    return None
                return data
            except json.JSONDecodeError:
                print(f"[JSExecutor] Spider 输出非 JSON: {stdout[:200]}")
                return None

        except subprocess.TimeoutExpired:
            print(f"[JSExecutor] Spider 执行超时 ({self.timeout}s)")
            return None
        except Exception as e:
            print(f"[JSExecutor] 执行异常: {e}")
            return None
        finally:
            # 清理临时文件
            if tmp_file and os.path.exists(tmp_file):
                try:
                    os.remove(tmp_file)
                except OSError:
                    pass


# ============================================================
#  CMS API 直接调用（Fallback）
# ============================================================
class CMSApiCaller:
    """CMS 采集站 API 直接调用

    很多 type 3 站点底层也是标准的 CMS API，只是通过 spider 做了额外处理。
    当 JS 执行失败时，尝试直接调用标准 CMS API 格式:
        - ?ac=list        → 获取分类和列表
        - ?ac=detail      → 获取详情
        - ?ac=list&wd=xxx → 搜索
    """

    def __init__(self, http: HttpHelper):
        self.http = http

    def homeContent(self, api_url: str, filter: bool = True) -> Optional[dict]:
        """获取首页内容（分类 + 列表）"""
        try:
            url = api_url.rstrip('/') + '?ac=list'
            data = self.http.get_json(url)
            if not data:
                return None

            result = {
                'class': [],
                'list': [],
                'filters': {},
            }

            # 解析分类
            for cls in data.get('class', []):
                result['class'].append({
                    'type_id': str(cls.get('type_id', '')),
                    'type_name': cls.get('type_name', ''),
                })

            # 解析视频列表
            for vod in data.get('list', []):
                result['list'].append(self._parse_vod_item(vod))

            return result
        except Exception as e:
            print(f"[CMSApi] homeContent 失败: {e}")
            return None

    def homeVod(self, api_url: str) -> Optional[dict]:
        """获取首页推荐视频"""
        try:
            url = api_url.rstrip('/') + '?ac=detail'
            data = self.http.get_json(url)
            if not data:
                return None

            result = {'list': []}
            for vod in data.get('list', []):
                result['list'].append(self._parse_vod_detail(vod))
            return result
        except Exception as e:
            print(f"[CMSApi] homeVod 失败: {e}")
            return None

    def category(self, api_url: str, tid: str, pg: int = 1,
                 filter: bool = True, extend: dict = None) -> Optional[dict]:
        """获取分类页内容"""
        try:
            params = {
                'ac': 'list',
                't': tid,
                'pg': pg,
            }
            if extend:
                params.update(extend)

            url = api_url.rstrip('/')
            data = self.http.get_json(url, params=params)
            if not data:
                return None

            result = {
                'list': [],
                'page': pg,
                'pagecount': data.get('pagecount', 1),
                'limit': data.get('limit', 20),
                'total': data.get('total', 0),
            }

            for vod in data.get('list', []):
                result['list'].append(self._parse_vod_item(vod))

            return result
        except Exception as e:
            print(f"[CMSApi] category 失败: {e}")
            return None

    def detail(self, api_url: str, ids: str) -> Optional[dict]:
        """获取视频详情"""
        try:
            url = api_url.rstrip('/') + f'?ac=detail&ids={ids}'
            data = self.http.get_json(url)
            if not data:
                return None

            vod_list = data.get('list', [])
            if not vod_list:
                return None

            vod = vod_list[0]
            result = self._parse_vod_detail(vod)
            return {'list': [result]}
        except Exception as e:
            print(f"[CMSApi] detail 失败: {e}")
            return None

    def search(self, api_url: str, keyword: str, quick: bool = True) -> Optional[dict]:
        """搜索影视"""
        try:
            params = {
                'ac': 'list',
                'wd': keyword,
            }
            url = api_url.rstrip('/')
            data = self.http.get_json(url, params=params)
            if not data:
                return None

            result = {'list': []}
            for vod in data.get('list', []):
                result['list'].append(self._parse_vod_item(vod))
            return result
        except Exception as e:
            print(f"[CMSApi] search 失败: {e}")
            return None

    def play(self, api_url: str, flag: str, id: str, flags: list = None) -> Optional[dict]:
        """解析播放地址（CMS 站点通常直接返回 URL）"""
        # CMS 站点的播放地址通常在 detail 中已经解析好
        # 这里返回一个标准格式
        return {
            'parse': 0,  # 0=直接播放, 1=需要解析
            'playUrl': '',
            'url': id,   # id 通常就是播放 URL
            'header': {},
        }

    def _parse_vod_item(self, vod: dict) -> dict:
        """解析视频列表项（简略信息）"""
        return {
            'vod_id': str(vod.get('vod_id', '')),
            'vod_name': vod.get('vod_name', ''),
            'vod_pic': vod.get('vod_pic', ''),
            'vod_remarks': vod.get('vod_remarks', ''),
            'type_name': vod.get('type_name', ''),
            'vod_year': vod.get('vod_year', ''),
            'vod_area': vod.get('vod_area', ''),
        }

    def _parse_vod_detail(self, vod: dict) -> dict:
        """解析视频详情（完整信息）"""
        result = self._parse_vod_item(vod)
        result.update({
            'vod_content': vod.get('vod_content', ''),
            'vod_director': vod.get('vod_director', ''),
            'vod_actor': vod.get('vod_actor', ''),
            'vod_play_from': vod.get('vod_play_from', ''),
            'vod_play_url': vod.get('vod_play_url', ''),
        })
        return result


# ============================================================
#  Spider 引擎主类
# ============================================================
class SpiderEngine:
    """TVBox JS Spider 执行引擎

    主要功能:
    1. 下载并缓存 Spider JS 文件
    2. 通过 Node.js 执行 Spider，获取数据
    3. 当 JS 执行失败时，自动降级为 CMS API 直接调用
    4. 支持标准 TVBox Spider 接口

    使用方式:
        engine = SpiderEngine()

        # 方式1: 通过 spider_url + api 指定
        result = engine.homeContent(spider_url='http://example.com/spider.js',
                                     api_url='http://example.com/api.php',
                                     api_name='csp_XXX')

        # 方式2: 通过 TVBox 站点配置
        result = engine.call_site_method(site_config, 'homeContent', filter=True)
    """

    def __init__(self, cache_dir: str = CACHE_DIR):
        """
        Args:
            cache_dir: Spider 文件缓存目录
        """
        self.http = HttpHelper()
        self.cache = SpiderCache(cache_dir)
        self.js_executor = JSExecutor()
        self.cms_caller = CMSApiCaller(self.http)

        # 已加载的 spider 缓存: {url: spider_code}
        self._loaded_spiders: Dict[str, str] = {}

        print(f"[SpiderEngine] 初始化完成")
        print(f"  缓存目录: {cache_dir}")
        print(f"  Node.js: {'可用' if self.js_executor.available else '不可用'}")

    # --------------------------------------------------------
    #  Spider 文件管理
    # --------------------------------------------------------
    def download_spider(self, spider_url: str) -> Optional[str]:
        """下载 Spider 文件（带缓存）

        Args:
            spider_url: Spider 文件的 URL

        Returns:
            Spider JS 文件内容，失败返回 None
        """
        if not spider_url:
            return None

        # 检查内存缓存
        if spider_url in self._loaded_spiders:
            return self._loaded_spiders[spider_url]

        # 检查磁盘缓存
        cached = self.cache.get_cached_content(spider_url)
        if cached:
            self._loaded_spiders[spider_url] = cached
            return cached

        # 下载
        print(f"[SpiderEngine] 下载 Spider: {spider_url}")
        content = self.http.get(spider_url)
        if not content:
            print(f"[SpiderEngine] 下载 Spider 失败: {spider_url}")
            return None

        # 基本验证: JS 文件应该不太小
        if len(content) < 50:
            print(f"[SpiderEngine] Spider 文件太小，可能无效 ({len(content)} bytes)")
            return None

        # 保存到缓存
        self.cache.save(spider_url, content)
        self._loaded_spiders[spider_url] = content

        return content

    def _get_spider_class_name(self, api_url: str) -> str:
        """从 api URL 中提取 Spider 类名

        TVBox 中 type 3 站点的 api 字段格式: csp_XXX
        返回 XXX 作为类名
        """
        if not api_url:
            return ''
        # api_url 可能是 'csp_XXX' 或完整 URL
        if api_url.startswith('csp_'):
            return api_url
        # 从 URL 路径中提取
        parsed = urlparse(api_url)
        path = parsed.path
        if 'csp_' in path:
            match = re.search(r'csp_(\w+)', path)
            if match:
                return f'csp_{match.group(1)}'
        return ''

    def _extract_api_url_from_spider(self, spider_code: str) -> Optional[str]:
        """尝试从 Spider 代码中提取 API 基础 URL

        很多 Spider 会在代码中定义 HOST 或 API 地址
        """
        # 常见模式: var HOST = 'http://xxx';
        patterns = [
            r'(?:var|let|const)\s+HOST\s*=\s*[\'"]([^\'"]+)[\'"]',
            r'(?:var|let|const)\s+API_URL\s*=\s*[\'"]([^\'"]+)[\'"]',
            r'(?:var|let|const)\s+BASE_URL\s*=\s*[\'"]([^\'"]+)[\'"]',
            r'(?:var|let|const)\s+host\s*=\s*[\'"]([^\'"]+)[\'"]',
            r'(?:var|let|const)\s+url\s*=\s*[\'"]((?:https?://)[^\'"]+)[\'"]',
        ]
        for pattern in patterns:
            match = re.search(pattern, spider_code)
            if match:
                url = match.group(1).rstrip('/')
                if url.startswith('http'):
                    return url
        return None

    # --------------------------------------------------------
    #  标准 Spider 接口
    # --------------------------------------------------------
    def _call_spider(self, spider_url: str, api_url: str, method: str,
                     params: dict = None) -> Optional[dict]:
        """调用 Spider 的指定方法

        执行流程:
        1. 下载/加载 Spider JS 文件
        2. 通过 Node.js 执行
        3. 如果失败，降级为 CMS API 调用

        Args:
            spider_url: Spider 文件 URL
            api_url: API 基础 URL（用于 CMS fallback）
            method: 方法名
            params: 方法参数

        Returns:
            JSON 结果，失败返回 None
        """
        result = None

        # 1. 尝试 JS Spider 执行
        if self.js_executor.available and spider_url:
            spider_code = self.download_spider(spider_url)
            if spider_code:
                class_name = self._get_spider_class_name(api_url)
                # 如果 api_url 是 csp_XXX 格式，尝试从 spider 代码提取真实 URL
                real_api = api_url
                if api_url.startswith('csp_'):
                    extracted = self._extract_api_url_from_spider(spider_code)
                    if extracted:
                        real_api = extracted

                print(f"[SpiderEngine] 执行 JS Spider: {method} (class={class_name})")
                result = self.js_executor.execute(
                    spider_code=spider_code,
                    method=method,
                    params=params,
                    class_name=class_name
                )

                if result and not result.get('error'):
                    return result
                else:
                    print(f"[SpiderEngine] JS Spider 执行失败，尝试 CMS API 降级")

        # 2. CMS API 降级
        # 确定实际的 API URL
        fallback_url = api_url
        if api_url.startswith('csp_'):
            # 尝试从已下载的 spider 中提取 URL
            if spider_url and spider_url in self._loaded_spiders:
                extracted = self._extract_api_url_from_spider(self._loaded_spiders[spider_url])
                if extracted:
                    fallback_url = extracted

        if fallback_url and not fallback_url.startswith('csp_'):
            print(f"[SpiderEngine] CMS API 降级: {method} → {fallback_url}")
            result = self._call_cms(fallback_url, method, params)

        return result

    def _call_cms(self, api_url: str, method: str, params: dict = None) -> Optional[dict]:
        """调用 CMS API"""
        params = params or {}
        try:
            if method == 'homeContent':
                return self.cms_caller.homeContent(api_url, params.get('filter', True))
            elif method == 'homeVod':
                return self.cms_caller.homeVod(api_url)
            elif method == 'category':
                return self.cms_caller.category(
                    api_url,
                    tid=params.get('tid', ''),
                    pg=params.get('pg', 1),
                    filter=params.get('filter', True),
                    extend=params.get('extend')
                )
            elif method == 'detail':
                return self.cms_caller.detail(api_url, ids=params.get('ids', ''))
            elif method == 'search':
                return self.cms_caller.search(api_url, keyword=params.get('wd', ''))
            elif method == 'play':
                return self.cms_caller.play(
                    api_url,
                    flag=params.get('flag', ''),
                    id=params.get('id', ''),
                    flags=params.get('flags')
                )
            else:
                print(f"[SpiderEngine] CMS 不支持方法: {method}")
                return None
        except Exception as e:
            print(f"[SpiderEngine] CMS 调用异常: {e}")
            return None

    # --------------------------------------------------------
    #  公开接口：标准 Spider 方法
    # --------------------------------------------------------
    def homeContent(self, spider_url: str = '', api_url: str = '',
                    filter: bool = True) -> Optional[dict]:
        """获取首页分类和推荐内容

        Args:
            spider_url: Spider 文件 URL
            api_url: API 基础 URL
            filter: 是否启用筛选

        Returns:
            {
                'class': [{'type_id': '1', 'type_name': '电影'}, ...],
                'list': [{'vod_id': '...', 'vod_name': '...', ...}, ...],
                'filters': {type_id: [{key, name, value}], ...}
            }
        """
        return self._call_spider(spider_url, api_url, 'homeContent', {
            'filter': filter,
        })

    def homeVod(self, spider_url: str = '', api_url: str = '') -> Optional[dict]:
        """获取首页推荐视频

        Returns:
            {'list': [{'vod_id': '...', 'vod_name': '...', ...}, ...]}
        """
        return self._call_spider(spider_url, api_url, 'homeVod')

    def category(self, spider_url: str = '', api_url: str = '',
                 tid: str = '', pg: int = 1, filter: bool = True,
                 extend: dict = None) -> Optional[dict]:
        """获取分类页内容

        Args:
            spider_url: Spider 文件 URL
            api_url: API 基础 URL
            tid: 分类 ID
            pg: 页码
            filter: 是否启用筛选
            extend: 扩展筛选参数

        Returns:
            {
                'list': [{'vod_id': '...', 'vod_name': '...', ...}, ...],
                'page': 1,
                'pagecount': 10,
                'total': 200
            }
        """
        return self._call_spider(spider_url, api_url, 'category', {
            'tid': tid,
            'pg': pg,
            'filter': filter,
            'extend': extend or {},
        })

    def detail(self, spider_url: str = '', api_url: str = '',
               ids: str = '') -> Optional[dict]:
        """获取视频详情（含播放地址）

        Args:
            spider_url: Spider 文件 URL
            api_url: API 基础 URL
            ids: 视频 ID（多个用逗号分隔）

        Returns:
            {
                'list': [{
                    'vod_id': '...',
                    'vod_name': '...',
                    'vod_pic': '...',
                    'vod_play_from': '线路1$$$线路2',
                    'vod_play_url': '第1集$url1#第2集$url2$$$第1集$url3#第2集$url4',
                    ...
                }]
            }
        """
        return self._call_spider(spider_url, api_url, 'detail', {
            'ids': ids,
        })

    def play(self, spider_url: str = '', api_url: str = '',
             flag: str = '', id: str = '', flags: list = None) -> Optional[dict]:
        """解析播放地址

        Args:
            spider_url: Spider 文件 URL
            api_url: API 基础 URL
            flag: 播放源名称
            id: 播放地址（可能是需要二次解析的 URL）
            flags: 所有可用播放源列表

        Returns:
            {
                'parse': 0,       # 0=直接播放, 1=需要解析
                'playUrl': '',    # 解析后的播放 URL
                'url': '...',     # 实际播放地址
                'header': {},     # 请求头
            }
        """
        return self._call_spider(spider_url, api_url, 'play', {
            'flag': flag,
            'id': id,
            'flags': flags or [],
        })

    def search(self, spider_url: str = '', api_url: str = '',
               keyword: str = '', quick: bool = True) -> Optional[dict]:
        """搜索影视

        Args:
            spider_url: Spider 文件 URL
            api_url: API 基础 URL
            keyword: 搜索关键词
            quick: 是否快速搜索

        Returns:
            {'list': [{'vod_id': '...', 'vod_name': '...', ...}, ...]}
        """
        return self._call_spider(spider_url, api_url, 'search', {
            'wd': keyword,
            'quick': quick,
        })

    # --------------------------------------------------------
    #  便捷方法：通过 TVBox 站点配置调用
    # --------------------------------------------------------
    def call_site_method(self, site: dict, spider_url: str,
                         method: str, **kwargs) -> Optional[dict]:
        """通过 TVBox 站点配置调用 Spider 方法

        Args:
            site: TVBox 站点配置字典，包含 api, type 等
            spider_url: Spider 文件 URL（从订阅源的 spider 字段获取）
            method: 方法名
            **kwargs: 方法参数

        Returns:
            方法返回结果
        """
        api_url = site.get('api', '')
        site_type = site.get('type', 0)

        # type 0/1 站点直接用 CMS API
        if site_type in (0, 1):
            return self._call_cms(api_url, method, kwargs)

        # type 3 站点用 Spider
        if site_type == 3:
            return self._call_spider(spider_url, api_url, method, kwargs)

        # type 4 站点（有时也用 Spider）
        if site_type == 4:
            return self._call_spider(spider_url, api_url, method, kwargs)

        print(f"[SpiderEngine] 不支持的站点类型: {site_type}")
        return None

    def get_site_api_url(self, site: dict, spider_url: str = '') -> str:
        """获取站点的实际 API URL

        对于 csp_XXX 格式的 api，尝试从 spider 中提取真实 URL

        Args:
            site: 站点配置
            spider_url: Spider 文件 URL

        Returns:
            实际可用的 API URL
        """
        api_url = site.get('api', '')

        # 如果不是 csp_ 格式，直接返回
        if not api_url.startswith('csp_'):
            return api_url

        # 尝试从 spider 中提取
        if spider_url:
            spider_code = self.download_spider(spider_url)
            if spider_code:
                extracted = self._extract_api_url_from_spider(spider_code)
                if extracted:
                    return extracted

        return api_url

    # --------------------------------------------------------
    #  缓存管理
    # --------------------------------------------------------
    def clear_cache(self):
        """清空 Spider 文件缓存"""
        self.cache.clear_all()
        self._loaded_spiders.clear()

    def get_cache_info(self) -> dict:
        """获取缓存信息"""
        import glob
        js_files = glob.glob(os.path.join(self.cache.cache_dir, "*.js"))
        meta_files = glob.glob(os.path.join(self.cache.cache_dir, "*.meta.json"))

        total_size = 0
        for f in js_files + meta_files:
            try:
                total_size += os.path.getsize(f)
            except OSError:
                pass

        return {
            'cache_dir': self.cache.cache_dir,
            'spider_count': len(js_files),
            'total_size': total_size,
            'total_size_mb': round(total_size / 1024 / 1024, 2),
        }


# ============================================================
#  工具函数
# ============================================================
def parse_play_sources(vod_play_from: str, vod_play_url: str) -> list:
    """解析播放线路和剧集列表

    Args:
        vod_play_from: 线路名称，$$$ 分隔
        vod_play_url: 播放地址，$$$ 分隔线路，# 分隔剧集，$ 分隔名称和URL

    Returns:
        [{'name': '线路1', 'episodes': [{'name': '第1集', 'url': '...'}, ...]}, ...]
    """
    if not vod_play_from or not vod_play_url:
        return []

    sources = []
    source_names = vod_play_from.split('$$$')
    source_urls = vod_play_url.split('$$$')

    for i, src_name in enumerate(source_names):
        src_name = src_name.strip()
        if not src_name:
            continue

        episodes = []
        if i < len(source_urls):
            ep_str = source_urls[i].strip()
            for ep_part in ep_str.split('#'):
                ep_part = ep_part.strip()
                if '$' in ep_part:
                    ep_name, ep_url = ep_part.split('$', 1)
                    ep_name = ep_name.strip()
                    ep_url = ep_url.strip()
                    if ep_name and ep_url:
                        episodes.append({
                            'name': ep_name,
                            'url': ep_url,
                        })

        if episodes:
            sources.append({
                'name': src_name,
                'episodes': episodes,
            })

    return sources


# ============================================================
#  测试入口
# ============================================================
if __name__ == '__main__':
    """简单测试"""
    engine = SpiderEngine()

    print("\n" + "=" * 50)
    print("SpiderEngine 测试")
    print("=" * 50)

    # 显示缓存信息
    info = engine.get_cache_info()
    print(f"\n缓存信息: {info}")

    # 测试 CMS API 调用
    test_url = "https://json.heimuer.xyz/api.php/provide/vod/"
    print(f"\n测试 CMS API: {test_url}")

    result = engine.cms_caller.homeContent(test_url)
    if result:
        categories = result.get('class', [])
        vod_list = result.get('list', [])
        print(f"  分类数: {len(categories)}")
        print(f"  视频数: {len(vod_list)}")
        if categories:
            print(f"  第一个分类: {categories[0]}")
        if vod_list:
            print(f"  第一个视频: {vod_list[0].get('vod_name', 'N/A')}")
    else:
        print("  调用失败")

    print("\n测试完成")
