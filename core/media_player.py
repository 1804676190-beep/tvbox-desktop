#!/usr/bin/env python3
"""TVBox Desktop — mpv 播放器封装"""

import sys
import platform


class MediaPlayer:
    """基于 python-mpv 的播放器封装"""

    def __init__(self):
        self._mpv = None
        self._on_end_callback = None

    def init_player(self, wid=None) -> bool:
        """
        初始化 mpv，嵌入到 Qt 窗口
        wid: 窗口句柄（Windows 下为 HWND）
        """
        try:
            import mpv

            args = {
                'idle': True,
                'keep_open': True,
                'input_default_bindings': False,
                'input_vo_keyboard': False,
                'osd_level': 0,
            }

            # Windows 特殊配置
            if platform.system() == 'Windows':
                args['vo'] = 'gpu'
                args['gpu-context'] = 'd3d11'
            else:
                args['vo'] = 'gpu'

            if wid is not None:
                args['wid'] = str(wid)

            self._mpv = mpv.MPV(**args)

            # 注册播放结束回调
            @self._mpv.event_callback('end-file')
            def on_end(event):
                if self._on_end_callback:
                    self._on_end_callback()

            return True
        except Exception as e:
            print(f"[MediaPlayer] 初始化失败: {e}")
            return False

    def play(self, url: str, title: str = ""):
        """播放指定 URL"""
        if not self._mpv:
            return
        try:
            self._mpv.stop()
            self._mpv.play(url)
            if title:
                self._mpv.title = title
        except Exception as e:
            print(f"[MediaPlayer] 播放失败: {e}")

    def stop(self):
        """停止播放"""
        if self._mpv:
            try:
                self._mpv.stop()
            except Exception:
                pass

    def pause(self):
        """暂停/恢复"""
        if self._mpv:
            try:
                self._mpv.cycle('pause')
            except Exception:
                pass

    @property
    def paused(self) -> bool:
        if self._mpv:
            try:
                return self._mpv.pause
            except Exception:
                pass
        return False

    def set_volume(self, vol: int):
        """设置音量 0-100"""
        if self._mpv:
            try:
                self._mpv.volume = max(0, min(100, vol))
            except Exception:
                pass

    @property
    def volume(self) -> int:
        if self._mpv:
            try:
                return int(self._mpv.volume)
            except Exception:
                pass
        return 50

    def seek(self, seconds: float):
        """跳转到指定秒数"""
        if self._mpv:
            try:
                self._mpv.seek(seconds, 'absolute')
            except Exception:
                pass

    def seek_relative(self, seconds: float):
        """相对跳转"""
        if self._mpv:
            try:
                self._mpv.seek(seconds, 'relative')
            except Exception:
                pass

    def set_on_end(self, callback):
        """设置播放结束回调"""
        self._on_end_callback = callback

    def get_property(self, name: str):
        """获取 mpv 属性"""
        if self._mpv:
            try:
                return self._mpv._get_property(name)
            except Exception:
                pass
        return None

    @property
    def duration(self) -> float:
        """总时长（秒）"""
        val = self.get_property('duration')
        return float(val) if val else 0

    @property
    def time_pos(self) -> float:
        """当前播放位置（秒）"""
        val = self.get_property('time-pos')
        return float(val) if val else 0

    @property
    def is_idle(self) -> bool:
        """是否空闲"""
        val = self.get_property('idle-active')
        return bool(val) if val is not None else True

    def toggle_fullscreen(self):
        """切换全屏"""
        if self._mpv:
            try:
                self._mpv.cycle('fullscreen')
            except Exception:
                pass

    def shutdown(self):
        """关闭播放器"""
        if self._mpv:
            try:
                self._mpv.terminate()
            except Exception:
                pass
            self._mpv = None
