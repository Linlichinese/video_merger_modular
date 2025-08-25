"""
临时文件管理器模块

专门管理视频处理过程中产生的各种临时文件，
特别针对MoviePy和FFmpeg产生的临时文件进行智能清理
"""

import os
import time
import glob
import threading
import tempfile
from typing import List, Dict, Set, Optional
from datetime import datetime, timedelta


class TempFileManager:
    """临时文件管理器 - 智能管理和清理临时文件"""
    
    def __init__(self, base_dirs: List[str] = None):
        """
        初始化临时文件管理器
        
        Args:
            base_dirs: 需要监控的基础目录列表
        """
        self.base_dirs = base_dirs or []
        self.registered_files: Set[str] = set()
        self.file_metadata: Dict[str, dict] = {}
        self._lock = threading.RLock()
        
        # 临时文件模式
        self.temp_patterns = {
            'moviepy': [
                '*TEMP_MPY_*',
                '*_temp_audiofile_*',
                '*_temp_videofile_*',
                '*_preview_*',
                '*_TEMP_*'
            ],
            'ffmpeg': [
                '*.tmp',
                '*_temp.*',
                'ffmpeg_*',
                '*_ffmpeg_*'
            ],
            'system': [
                '*.partial',
                '*.downloading',
                '*~',
                '.tmp*'
            ]
        }
    
    def register_temp_file(self, file_path: str, source: str = 'unknown', 
                          auto_cleanup: bool = True, max_age_hours: int = 24):
        """
        注册临时文件
        
        Args:
            file_path: 临时文件路径
            source: 文件来源（如 'moviepy', 'ffmpeg'等）
            auto_cleanup: 是否自动清理
            max_age_hours: 最大保留时间（小时）
        """
        with self._lock:
            self.registered_files.add(file_path)
            self.file_metadata[file_path] = {
                'source': source,
                'created_time': datetime.now(),
                'auto_cleanup': auto_cleanup,
                'max_age_hours': max_age_hours,
                'size': self._get_file_size(file_path)
            }
            print(f"[TempFileManager] 注册临时文件: {file_path} (来源: {source})")
    
    def scan_temp_files(self, base_dir: str = None) -> List[str]:
        """
        扫描指定目录中的临时文件
        
        Args:
            base_dir: 扫描目录，如果为None则扫描所有注册的基础目录
            
        Returns:
            发现的临时文件列表
        """
        temp_files = []
        dirs_to_scan = [base_dir] if base_dir else self.base_dirs
        
        for directory in dirs_to_scan:
            if not os.path.exists(directory):
                continue
                
            print(f"[TempFileManager] 扫描临时文件目录: {directory}")
            
            for category, patterns in self.temp_patterns.items():
                for pattern in patterns:
                    try:
                        found_files = glob.glob(os.path.join(directory, "**", pattern), recursive=True)
                        for file_path in found_files:
                            if os.path.isfile(file_path):
                                temp_files.append(file_path)
                                # 自动注册发现的临时文件
                                if file_path not in self.registered_files:
                                    self.register_temp_file(file_path, category, auto_cleanup=True)
                    except Exception as e:
                        print(f"[TempFileManager] 扫描模式失败 {pattern}: {e}")
        
        print(f"[TempFileManager] 发现 {len(temp_files)} 个临时文件")
        return temp_files
    
    def cleanup_expired_files(self) -> int:
        """
        清理过期的临时文件
        
        Returns:
            成功清理的文件数量
        """
        current_time = datetime.now()
        cleaned_count = 0
        
        with self._lock:
            expired_files = []
            
            for file_path, metadata in self.file_metadata.items():
                if not metadata.get('auto_cleanup', True):
                    continue
                    
                age = current_time - metadata['created_time']
                max_age = timedelta(hours=metadata.get('max_age_hours', 24))
                
                if age > max_age:
                    expired_files.append(file_path)
            
            print(f"[TempFileManager] 发现 {len(expired_files)} 个过期临时文件")
            
            for file_path in expired_files:
                if self._delete_temp_file(file_path):
                    cleaned_count += 1
                    self._unregister_file(file_path)
        
        return cleaned_count
    
    def cleanup_by_pattern(self, pattern: str, base_dir: str = None) -> int:
        """
        按模式清理临时文件
        
        Args:
            pattern: 文件模式（如 '*TEMP_MPY_*'）
            base_dir: 基础目录
            
        Returns:
            成功清理的文件数量
        """
        cleaned_count = 0
        dirs_to_clean = [base_dir] if base_dir else self.base_dirs
        
        for directory in dirs_to_clean:
            if not os.path.exists(directory):
                continue
                
            try:
                files_to_clean = glob.glob(os.path.join(directory, "**", pattern), recursive=True)
                print(f"[TempFileManager] 在 {directory} 中发现 {len(files_to_clean)} 个匹配 {pattern} 的文件")
                
                for file_path in files_to_clean:
                    if os.path.isfile(file_path):
                        if self._delete_temp_file(file_path):
                            cleaned_count += 1
                            self._unregister_file(file_path)
                            
            except Exception as e:
                print(f"[TempFileManager] 按模式清理失败 {pattern}: {e}")
        
        return cleaned_count
    
    def cleanup_moviepy_files(self, base_dir: str = None) -> int:
        """
        专门清理MoviePy临时文件
        
        Args:
            base_dir: 基础目录
            
        Returns:
            成功清理的文件数量
        """
        total_cleaned = 0
        
        print("[TempFileManager] 开始清理MoviePy临时文件...")
        
        for pattern in self.temp_patterns['moviepy']:
            cleaned = self.cleanup_by_pattern(pattern, base_dir)
            total_cleaned += cleaned
            if cleaned > 0:
                print(f"[TempFileManager] 模式 {pattern} 清理了 {cleaned} 个文件")
        
        # 额外等待，确保文件句柄释放
        time.sleep(1.0)
        
        print(f"[TempFileManager] MoviePy临时文件清理完成，共清理 {total_cleaned} 个文件")
        return total_cleaned
    
    def force_cleanup_all(self, base_dir: str = None) -> int:
        """
        强制清理所有临时文件
        
        Args:
            base_dir: 基础目录
            
        Returns:
            成功清理的文件数量
        """
        print("[TempFileManager] 开始强制清理所有临时文件...")
        
        total_cleaned = 0
        
        # 先扫描所有临时文件
        self.scan_temp_files(base_dir)
        
        # 按类别清理
        for category in self.temp_patterns.keys():
            category_cleaned = 0
            for pattern in self.temp_patterns[category]:
                cleaned = self.cleanup_by_pattern(pattern, base_dir)
                category_cleaned += cleaned
            
            if category_cleaned > 0:
                print(f"[TempFileManager] {category} 类别清理了 {category_cleaned} 个文件")
            total_cleaned += category_cleaned
        
        # 清理注册的文件
        with self._lock:
            registered_cleaned = 0
            for file_path in list(self.registered_files):
                if base_dir is None or file_path.startswith(base_dir):
                    if self._delete_temp_file(file_path):
                        registered_cleaned += 1
                        self._unregister_file(file_path)
            
            if registered_cleaned > 0:
                print(f"[TempFileManager] 注册文件清理了 {registered_cleaned} 个文件")
            total_cleaned += registered_cleaned
        
        print(f"[TempFileManager] 强制清理完成，共清理 {total_cleaned} 个文件")
        return total_cleaned
    
    def get_temp_file_info(self) -> Dict[str, dict]:
        """
        获取临时文件信息
        
        Returns:
            临时文件信息字典
        """
        with self._lock:
            info = {
                'total_files': len(self.registered_files),
                'total_size': sum(metadata.get('size', 0) for metadata in self.file_metadata.values()),
                'by_source': {},
                'oldest_file': None,
                'largest_file': None
            }
            
            # 按来源统计
            for file_path, metadata in self.file_metadata.items():
                source = metadata.get('source', 'unknown')
                if source not in info['by_source']:
                    info['by_source'][source] = {'count': 0, 'size': 0}
                info['by_source'][source]['count'] += 1
                info['by_source'][source]['size'] += metadata.get('size', 0)
            
            # 找到最老和最大的文件
            if self.file_metadata:
                oldest = min(self.file_metadata.items(), key=lambda x: x[1]['created_time'])
                largest = max(self.file_metadata.items(), key=lambda x: x[1].get('size', 0))
                info['oldest_file'] = {'path': oldest[0], **oldest[1]}
                info['largest_file'] = {'path': largest[0], **largest[1]}
            
            return info
    
    def _delete_temp_file(self, file_path: str, max_retries: int = 5) -> bool:
        """
        删除临时文件，带重试机制
        
        Args:
            file_path: 文件路径
            max_retries: 最大重试次数
            
        Returns:
            是否成功删除
        """
        if not os.path.exists(file_path):
            return True
        
        for attempt in range(max_retries):
            try:
                os.unlink(file_path)
                print(f"[TempFileManager] 成功删除临时文件: {file_path}")
                return True
                
            except PermissionError as e:
                if "WinError 32" in str(e) or "being used by another process" in str(e):
                    if attempt < max_retries - 1:
                        wait_time = 0.5 * (2 ** attempt)  # 指数退避
                        print(f"[TempFileManager] 文件被占用，等待 {wait_time}s 后重试: {file_path}")
                        time.sleep(wait_time)
                        continue
                    else:
                        print(f"[TempFileManager] 文件删除失败，文件被占用: {file_path}")
                        return False
                else:
                    print(f"[TempFileManager] 权限错误: {file_path}, {e}")
                    return False
                    
            except Exception as e:
                print(f"[TempFileManager] 删除临时文件失败: {file_path}, {e}")
                return False
        
        return False
    
    def _get_file_size(self, file_path: str) -> int:
        """获取文件大小"""
        try:
            return os.path.getsize(file_path) if os.path.exists(file_path) else 0
        except Exception:
            return 0
    
    def _unregister_file(self, file_path: str):
        """从注册列表中移除文件"""
        self.registered_files.discard(file_path)
        self.file_metadata.pop(file_path, None)
    
    def add_base_directory(self, directory: str):
        """添加基础监控目录"""
        if directory not in self.base_dirs:
            self.base_dirs.append(directory)
            print(f"[TempFileManager] 添加监控目录: {directory}")
    
    def remove_base_directory(self, directory: str):
        """移除基础监控目录"""
        if directory in self.base_dirs:
            self.base_dirs.remove(directory)
            print(f"[TempFileManager] 移除监控目录: {directory}")


# 全局临时文件管理器实例
global_temp_manager = TempFileManager()


def get_temp_manager() -> TempFileManager:
    """获取全局临时文件管理器实例"""
    return global_temp_manager


def cleanup_temp_files_in_directory(directory: str) -> int:
    """
    清理指定目录中的临时文件
    
    Args:
        directory: 目录路径
        
    Returns:
        清理的文件数量
    """
    temp_manager = get_temp_manager()
    temp_manager.add_base_directory(directory)
    return temp_manager.force_cleanup_all(directory)
