"""
资源管理器模块

提供强健的资源清理和文件句柄管理，解决WinError 32等文件占用问题
"""

import os
import gc
import time
import psutil
import threading
import subprocess
import glob
import re
from typing import List, Dict, Optional, Callable
from contextlib import contextmanager


class ResourceManager:
    """资源管理器 - 统一管理视频处理过程中的所有资源"""
    
    def __init__(self):
        self._active_clips = []  # 活跃的视频剪辑对象
        self._temp_files = []    # 临时文件列表
        self._processes = []     # 活跃进程列表
        self._audio_readers = [] # 活跃的音频读取器对象
        self._moviepy_temp_files = []  # MoviePy临时文件列表
        self._lock = threading.RLock()
    
    def register_clip(self, clip):
        """注册视频剪辑对象"""
        with self._lock:
            if clip not in self._active_clips:
                self._active_clips.append(clip)
    
    def register_temp_file(self, file_path: str):
        """注册临时文件"""
        with self._lock:
            if file_path not in self._temp_files:
                self._temp_files.append(file_path)
    
    def register_process(self, process):
        """注册进程"""
        with self._lock:
            if process not in self._processes:
                self._processes.append(process)
    
    def register_audio_reader(self, audio_reader):
        """注册音频读取器对象"""
        with self._lock:
            if audio_reader not in self._audio_readers:
                self._audio_readers.append(audio_reader)
                print(f"[ResourceManager] 注册音频读取器: {type(audio_reader).__name__}")
    
    def register_moviepy_temp_file(self, file_path: str):
        """注册MoviePy临时文件"""
        with self._lock:
            if file_path not in self._moviepy_temp_files:
                self._moviepy_temp_files.append(file_path)
                print(f"[ResourceManager] 注册MoviePy临时文件: {file_path}")
    
    def scan_and_register_moviepy_temp_files(self, base_dir: str):
        """扫描并注册目录中的MoviePy临时文件"""
        temp_patterns = [
            "*TEMP_MPY_*",
            "*_temp_audiofile_*", 
            "*_temp_videofile_*",
            "*_preview_*"
        ]
        
        with self._lock:
            for pattern in temp_patterns:
                temp_files = glob.glob(os.path.join(base_dir, "**", pattern), recursive=True)
                for temp_file in temp_files:
                    if temp_file not in self._moviepy_temp_files:
                        self._moviepy_temp_files.append(temp_file)
                        print(f"[ResourceManager] 发现并注册MoviePy临时文件: {temp_file}")
    
    def cleanup_all(self, force: bool = False):
        """清理所有资源"""
        with self._lock:
            print("[ResourceManager] 开始全面资源清理...")
            
            # 清理音频读取器（优先处理，避免文件占用）
            self._cleanup_audio_readers()
            
            # 清理视频剪辑
            self._cleanup_clips()
            
            # 清理进程
            self._cleanup_processes(force)
            
            # 强制终止FFmpeg进程
            if force:
                self._force_kill_ffmpeg_processes()
            
            # 强制垃圾回收
            gc.collect()
            
            # 等待一下让系统释放句柄
            time.sleep(1.0 if force else 0.5)
            
            # 清理MoviePy临时文件
            self._cleanup_moviepy_temp_files()
            
            # 清理临时文件
            self._cleanup_temp_files()
            
            print("[ResourceManager] 资源清理完成")
    
    def _cleanup_clips(self):
        """清理视频剪辑对象"""
        for clip in self._active_clips[:]:
            try:
                if hasattr(clip, 'close'):
                    clip.close()
                self._active_clips.remove(clip)
            except Exception as e:
                print(f"清理视频剪辑失败: {e}")
        
        # 清空列表
        self._active_clips.clear()
    
    def _cleanup_processes(self, force: bool = False):
        """清理进程"""
        for process in self._processes[:]:
            try:
                if process.poll() is None:  # 进程仍在运行
                    if force:
                        process.kill()
                    else:
                        process.terminate()
                    process.wait(timeout=2.0)
                self._processes.remove(process)
            except Exception as e:
                print(f"清理进程失败: {e}")
        
        # 清空列表
        self._processes.clear()
    
    def _cleanup_audio_readers(self):
        """清理音频读取器对象"""
        print(f"[ResourceManager] 清理 {len(self._audio_readers)} 个音频读取器")
        for reader in self._audio_readers[:]:
            try:
                # 尝试关闭音频读取器
                if hasattr(reader, 'close_proc'):
                    reader.close_proc()
                elif hasattr(reader, 'close'):
                    reader.close()
                self._audio_readers.remove(reader)
                print(f"[ResourceManager] 成功清理音频读取器: {type(reader).__name__}")
            except Exception as e:
                print(f"[ResourceManager] 清理音频读取器失败: {e}")
                # 即使失败也要从列表中移除
                if reader in self._audio_readers:
                    self._audio_readers.remove(reader)
        
        # 清空列表
        self._audio_readers.clear()
    
    def _cleanup_moviepy_temp_files(self):
        """清理MoviePy临时文件"""
        print(f"[ResourceManager] 清理 {len(self._moviepy_temp_files)} 个MoviePy临时文件")
        for file_path in self._moviepy_temp_files[:]:
            try:
                if os.path.exists(file_path):
                    # 使用增强的重试机制删除临时文件
                    self._delete_moviepy_temp_file_with_retry(file_path)
                    print(f"[ResourceManager] 成功清理MoviePy临时文件: {file_path}")
                self._moviepy_temp_files.remove(file_path)
            except Exception as e:
                print(f"[ResourceManager] 清理MoviePy临时文件失败 {file_path}: {e}")
        
        # 清空列表
        self._moviepy_temp_files.clear()
    
    def _force_kill_ffmpeg_processes(self):
        """强制终止所有FFmpeg进程"""
        try:
            print("[ResourceManager] 强制终止FFmpeg进程...")
            # 查找所有FFmpeg进程
            for proc in psutil.process_iter(['pid', 'name']):
                try:
                    if 'ffmpeg' in proc.info['name'].lower():
                        print(f"[ResourceManager] 终止FFmpeg进程 PID: {proc.info['pid']}")
                        proc.kill()
                        proc.wait(timeout=3)
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired):
                    pass
        except Exception as e:
            print(f"[ResourceManager] 强制终止FFmpeg进程失败: {e}")
    
    def _cleanup_temp_files(self):
        """清理临时文件"""
        for file_path in self._temp_files[:]:
            try:
                if os.path.exists(file_path):
                    # 使用重试机制删除文件
                    self._delete_file_with_retry(file_path)
                self._temp_files.remove(file_path)
            except Exception as e:
                print(f"清理临时文件失败 {file_path}: {e}")
        
        # 清空列表
        self._temp_files.clear()
    
    def _delete_file_with_retry(self, file_path: str, max_retries: int = 5):
        """使用重试机制删除文件"""
        for attempt in range(max_retries):
            try:
                os.unlink(file_path)
                return
            except PermissionError as e:
                if "WinError 32" in str(e) or "being used by another process" in str(e):
                    if attempt < max_retries - 1:
                        print(f"文件被占用，重试删除 ({attempt + 1}/{max_retries}): {file_path}")
                        time.sleep(0.5 * (attempt + 1))  # 逐渐增加等待时间
                        continue
                    else:
                        print(f"文件删除失败，可能仍被占用: {file_path}")
                        # 记录到待删除列表，稍后清理
                        self._schedule_delayed_cleanup(file_path)
                raise
            except Exception as e:
                print(f"删除文件失败: {file_path}, 错误: {e}")
                raise
    
    def _schedule_delayed_cleanup(self, file_path: str):
        """计划延迟清理文件"""
        def delayed_cleanup():
            time.sleep(5)  # 等待5秒
            try:
                if os.path.exists(file_path):
                    os.unlink(file_path)
                    print(f"延迟清理成功: {file_path}")
            except Exception as e:
                print(f"延迟清理失败: {file_path}, 错误: {e}")
        
        thread = threading.Thread(target=delayed_cleanup, daemon=True)
        thread.start()
    
    def _delete_moviepy_temp_file_with_retry(self, file_path: str, max_retries: int = 8):
        """使用增强重试机制删除MoviePy临时文件"""
        print(f"[ResourceManager] 尝试删除MoviePy临时文件: {file_path}")
        
        for attempt in range(max_retries):
            try:
                # 首先尝试强制解除文件锁定
                if attempt > 2:
                    self._unlock_file_handles(file_path)
                
                os.unlink(file_path)
                print(f"[ResourceManager] 成功删除MoviePy临时文件 (尝试 {attempt + 1}): {file_path}")
                return
                
            except PermissionError as e:
                if "WinError 32" in str(e) or "being used by another process" in str(e):
                    if attempt < max_retries - 1:
                        wait_time = min(2.0 ** attempt, 10.0)  # 指数退避，最大10秒
                        print(f"[ResourceManager] MoviePy临时文件被占用，等待 {wait_time}s 后重试 ({attempt + 1}/{max_retries}): {file_path}")
                        time.sleep(wait_time)
                        continue
                    else:
                        print(f"[ResourceManager] MoviePy临时文件删除失败，计划延迟清理: {file_path}")
                        self._schedule_delayed_cleanup(file_path)
                raise
            except Exception as e:
                print(f"[ResourceManager] 删除MoviePy临时文件失败: {file_path}, 错误: {e}")
                raise
    
    def _unlock_file_handles(self, file_path: str):
        """尝试解除文件句柄锁定"""
        try:
            # 在Windows上尝试使用handle工具或者通过进程查找
            if os.name == 'nt':  # Windows
                # 强制垃圾回收，可能释放一些句柄
                gc.collect()
                time.sleep(0.5)
                
                # 查找可能占用文件的Python进程
                file_name = os.path.basename(file_path)
                for proc in psutil.process_iter(['pid', 'name', 'open_files']):
                    try:
                        if proc.info['name'] and 'python' in proc.info['name'].lower():
                            if proc.info['open_files']:
                                for open_file in proc.info['open_files']:
                                    if file_name in open_file.path:
                                        print(f"[ResourceManager] 发现占用文件的进程 PID: {proc.info['pid']}")
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
        except Exception as e:
            print(f"[ResourceManager] 解除文件句柄锁定失败: {e}")
    
    def cleanup_with_winerror32_handling(self, base_dir: str):
        """专门处理WinError 32的清理方法"""
        print(f"[ResourceManager] 启动WinError 32专门处理，目录: {base_dir}")
        
        # 扫描并注册所有可能的临时文件
        self.scan_and_register_moviepy_temp_files(base_dir)
        
        # 强制清理资源
        self.cleanup_all(force=True)
        
        # 额外等待，确保文件句柄释放
        time.sleep(2.0)
        
        # 最后一次清理尝试
        self._final_cleanup_attempt(base_dir)
    
    def _final_cleanup_attempt(self, base_dir: str):
        """最后的清理尝试"""
        temp_patterns = ["*TEMP_MPY_*", "*_temp_audiofile_*", "*_temp_videofile_*"]
        
        for pattern in temp_patterns:
            remaining_files = glob.glob(os.path.join(base_dir, "**", pattern), recursive=True)
            for temp_file in remaining_files:
                try:
                    if os.path.exists(temp_file):
                        os.unlink(temp_file)
                        print(f"[ResourceManager] 最终清理成功: {temp_file}")
                except Exception as e:
                    print(f"[ResourceManager] 最终清理失败: {temp_file}, {e}")


@contextmanager
def managed_video_clip(video_path: str, resource_manager: ResourceManager = None):
    """上下文管理器，确保VideoFileClip正确关闭"""
    from moviepy.editor import VideoFileClip
    
    clip = None
    try:
        clip = VideoFileClip(video_path)
        if resource_manager:
            resource_manager.register_clip(clip)
        yield clip
    finally:
        if clip:
            try:
                clip.close()
                if resource_manager and clip in resource_manager._active_clips:
                    resource_manager._active_clips.remove(clip)
            except Exception as e:
                print(f"关闭视频剪辑失败: {e}")


@contextmanager
def managed_temp_file(file_path: str, resource_manager: ResourceManager = None):
    """上下文管理器，确保临时文件正确清理"""
    try:
        if resource_manager:
            resource_manager.register_temp_file(file_path)
        yield file_path
    finally:
        try:
            if os.path.exists(file_path):
                if resource_manager:
                    resource_manager._delete_file_with_retry(file_path)
                else:
                    os.unlink(file_path)
        except Exception as e:
            print(f"清理临时文件失败: {file_path}, 错误: {e}")


def force_cleanup_file_handles():
    """强制清理可能泄漏的文件句柄"""
    try:
        # 强制垃圾回收
        gc.collect()
        
        # 获取当前进程信息
        current_process = psutil.Process()
        
        # 打印文件句柄数量用于调试
        try:
            num_handles = current_process.num_handles() if hasattr(current_process, 'num_handles') else len(current_process.open_files())
            print(f"当前文件句柄数量: {num_handles}")
        except Exception:
            pass
        
    except Exception as e:
        print(f"清理文件句柄失败: {e}")


def check_file_access(file_path: str) -> bool:
    """检查文件是否可以访问（没有被其他进程占用）"""
    try:
        # 尝试以排他模式打开文件
        with open(file_path, 'r+b') as f:
            pass
        return True
    except (PermissionError, IOError):
        return False
    except Exception:
        return False


def wait_for_file_release(file_path: str, timeout: float = 10.0) -> bool:
    """等待文件被释放"""
    start_time = time.time()
    while time.time() - start_time < timeout:
        if check_file_access(file_path):
            return True
        time.sleep(0.1)
    return False

