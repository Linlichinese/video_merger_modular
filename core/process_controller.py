"""
进程控制器模块

统一管理FFmpeg子进程句柄、标准输出/错误与生命周期
支持优雅终止和强制终止，以及半成品文件清理
"""

import os
import subprocess
import threading
import time
import tempfile
from typing import List, Dict, Optional, Callable
from PyQt5.QtCore import QObject, pyqtSignal


class ProcessController(QObject):
    """FFmpeg进程控制器"""
    
    # 信号
    progress_updated = pyqtSignal(float)  # 进度更新信号 (0.0-1.0)
    process_error = pyqtSignal(str)       # 进程错误信号
    
    def __init__(self):
        super().__init__()
        self._active_processes: List[subprocess.Popen] = []
        self._temp_files: List[str] = []
        self._output_files: List[str] = []
        self._lock = threading.RLock()
        self._cancelled = False
        self._cleanup_on_cancel = True
        
    def add_process(self, process: subprocess.Popen, 
                   temp_files: List[str] = None, 
                   output_file: str = None) -> None:
        """
        添加一个活跃进程到管理列表
        
        Args:
            process: subprocess.Popen对象
            temp_files: 该进程相关的临时文件列表
            output_file: 该进程的输出文件路径
        """
        with self._lock:
            self._active_processes.append(process)
            if temp_files:
                self._temp_files.extend(temp_files)
            if output_file:
                self._output_files.append(output_file)
    
    def remove_process(self, process: subprocess.Popen) -> None:
        """从活跃进程列表中移除进程"""
        with self._lock:
            if process in self._active_processes:
                self._active_processes.remove(process)
    
    def cancel_all(self, timeout: float = 2.0) -> bool:
        """
        取消所有活跃进程
        
        Args:
            timeout: 优雅终止超时时间（秒）
            
        Returns:
            bool: 是否成功终止所有进程
        """
        with self._lock:
            self._cancelled = True
            
            if not self._active_processes:
                return True
            
            # 第一阶段：优雅终止
            for process in self._active_processes[:]:  # 创建副本避免迭代时修改
                if process.poll() is None:  # 进程仍在运行
                    try:
                        process.terminate()
                    except Exception:
                        pass  # 忽略终止错误
            
            # 等待优雅终止
            start_time = time.time()
            while time.time() - start_time < timeout:
                all_terminated = True
                for process in self._active_processes[:]:
                    if process.poll() is None:
                        all_terminated = False
                        break
                    else:
                        self._active_processes.remove(process)
                
                if all_terminated:
                    break
                time.sleep(0.1)
            
            # 第二阶段：强制终止
            for process in self._active_processes[:]:
                if process.poll() is None:
                    try:
                        process.kill()
                        process.wait(timeout=1.0)
                    except Exception:
                        pass
                    finally:
                        if process in self._active_processes:
                            self._active_processes.remove(process)
            
            # 清理半成品文件
            if self._cleanup_on_cancel:
                self._cleanup_files()
            
            return len(self._active_processes) == 0
    
    def _cleanup_files(self) -> None:
        """清理临时文件和不完整的输出文件"""
        # 清理临时文件
        for temp_file in self._temp_files:
            try:
                if os.path.exists(temp_file):
                    os.unlink(temp_file)
            except Exception:
                pass  # 忽略清理错误
        
        # 清理不完整的输出文件
        for output_file in self._output_files:
            try:
                if os.path.exists(output_file):
                    # 检查文件是否可能是不完整的（文件很小或修改时间很近）
                    stat = os.stat(output_file)
                    current_time = time.time()
                    
                    # 如果文件很小（<1MB）或者修改时间在最近30秒内，认为是不完整的
                    if stat.st_size < 1024 * 1024 or (current_time - stat.st_mtime) < 30:
                        os.unlink(output_file)
            except Exception:
                pass  # 忽略清理错误
        
        # 清理列表
        self._temp_files.clear()
        self._output_files.clear()
    
    def is_cancelled(self) -> bool:
        """检查是否已被取消"""
        return self._cancelled
    
    def reset(self) -> None:
        """重置控制器状态"""
        with self._lock:
            self._cancelled = False
            self._active_processes.clear()
            self._temp_files.clear()
            self._output_files.clear()
    
    def get_active_count(self) -> int:
        """获取活跃进程数量"""
        with self._lock:
            return len(self._active_processes)
    
    def set_cleanup_on_cancel(self, cleanup: bool) -> None:
        """设置取消时是否清理文件"""
        self._cleanup_on_cancel = cleanup


class FFmpegProgressMonitor:
    """FFmpeg进度监控器"""
    
    def __init__(self, process_controller: ProcessController):
        self.process_controller = process_controller
        
    def monitor_progress_pipe(self, process: subprocess.Popen, 
                            total_duration: float,
                            progress_callback: Optional[Callable[[float], None]] = None) -> None:
        """
        使用-progress pipe:1监控FFmpeg进度
        
        Args:
            process: FFmpeg进程
            total_duration: 总时长（秒）
            progress_callback: 进度回调函数，接收0.0-1.0的进度值
        """
        import threading
        from PyQt5.QtCore import QTimer, QObject
        
        def monitor():
            try:
                last_progress = 0.0
                while process.poll() is None and not self.process_controller.is_cancelled():
                    line = process.stdout.readline()
                    if not line:
                        continue
                        
                    line = line.strip()
                    if line.startswith('out_time_ms='):
                        try:
                            # 解析out_time_ms（微秒）
                            time_ms = int(line.split('=')[1])
                            current_time = time_ms / 1_000_000.0  # 转换为秒
                            
                            if total_duration > 0:
                                progress = min(current_time / total_duration, 1.0)
                                
                                # 只有当进度有明显变化时才发射信号（减少频繁更新）
                                if abs(progress - last_progress) >= 0.01:  # 至少1%的变化
                                    last_progress = progress
                                    
                                    # 使用QTimer在主线程中发射信号
                                    QTimer.singleShot(0, lambda p=progress: self._emit_progress_safely(p, progress_callback))
                                    
                        except (ValueError, IndexError):
                            continue
                            
            except Exception as e:
                if not self.process_controller.is_cancelled():
                    # 使用QTimer在主线程中发射错误信号
                    QTimer.singleShot(0, lambda: self.process_controller.process_error.emit(f"进度监控错误: {str(e)}"))
        
        # 在单独线程中监控
        monitor_thread = threading.Thread(target=monitor, daemon=True)
        monitor_thread.start()
    
    def _emit_progress_safely(self, progress: float, progress_callback: Optional[Callable[[float], None]] = None):
        """在主线程中安全发射进度信号"""
        try:
            # 发射信号
            self.process_controller.progress_updated.emit(progress)
            
            # 调用回调
            if progress_callback:
                progress_callback(progress)
        except Exception as e:
            print(f"进度信号发射失败: {e}")
        
    def get_video_duration(self, video_path: str) -> float:
        """
        使用ffprobe获取视频时长
        
        Args:
            video_path: 视频文件路径
            
        Returns:
            float: 视频时长（秒），失败时返回0
        """
        try:
            cmd = [
                'ffprobe', '-v', 'quiet', 
                '-show_entries', 'format=duration',
                '-of', 'csv=p=0', 
                video_path
            ]
            
            result = subprocess.run(
                cmd, 
                capture_output=True, 
                text=True, 
                timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            
            if result.returncode == 0 and result.stdout.strip():
                return float(result.stdout.strip())
                
        except Exception:
            pass
            
        return 0.0
    
    def get_total_duration_from_concat(self, concat_file: str) -> float:
        """
        从concat文件获取总时长
        
        Args:
            concat_file: FFmpeg concat文件路径
            
        Returns:
            float: 总时长（秒）
        """
        try:
            cmd = [
                'ffprobe', '-v', 'quiet',
                '-show_entries', 'format=duration',
                '-of', 'csv=p=0',
                '-f', 'concat', '-safe', '0',
                concat_file
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            
            if result.returncode == 0 and result.stdout.strip():
                return float(result.stdout.strip())
                
        except Exception:
            pass
            
        return 0.0


class FFmpegCommandBuilder:
    """FFmpeg命令构建器"""
    
    @staticmethod
    def build_progress_command(input_args: List[str], output_path: str, 
                             gpu_settings: Dict = None, 
                             video_settings: Dict = None,
                             audio_settings: Dict = None) -> List[str]:
        """
        构建带进度监控的FFmpeg命令
        
        Args:
            input_args: 输入参数列表
            output_path: 输出文件路径
            gpu_settings: GPU设置
            video_settings: 视频设置
            audio_settings: 音频设置
            
        Returns:
            List[str]: FFmpeg命令列表
        """
        cmd = ['ffmpeg', '-y']  # -y 覆盖输出文件
        
        # 添加进度输出到stdout
        cmd.extend(['-progress', 'pipe:1'])
        
        # 硬件解码器设置
        if gpu_settings and gpu_settings.get('hardware_decoder'):
            if 'nvenc' in gpu_settings.get('hardware_encoder', ''):
                cmd.extend(['-hwaccel', 'cuda'])
            elif 'qsv' in gpu_settings.get('hardware_encoder', ''):
                cmd.extend(['-hwaccel', 'qsv'])
            else:
                cmd.extend(['-hwaccel', 'auto'])
        
        # 输入参数
        cmd.extend(input_args)
        
        # 视频编码设置
        if gpu_settings and gpu_settings.get('hardware_encoder'):
            cmd.extend(['-c:v', gpu_settings['hardware_encoder']])
            
            # 编码器特定设置
            if 'nvenc' in gpu_settings['hardware_encoder']:
                cmd.extend([
                    '-preset', gpu_settings.get('preset', 'p4'),
                    '-rc', 'vbr',
                    '-cq', '23'
                ])
            elif 'qsv' in gpu_settings['hardware_encoder']:
                cmd.extend(['-preset', gpu_settings.get('preset', 'medium')])
            
            # 码率设置
            if video_settings and video_settings.get('bitrate'):
                cmd.extend(['-b:v', video_settings['bitrate']])
                if 'nvenc' in gpu_settings['hardware_encoder']:
                    bitrate_num = int(video_settings['bitrate'].rstrip('k'))
                    cmd.extend([
                        '-maxrate', f"{bitrate_num * 2}k",
                        '-bufsize', f"{bitrate_num * 2}k"
                    ])
        else:
            # CPU编码设置
            cmd.extend(['-c:v', 'libx264'])
            if video_settings:
                cmd.extend(['-preset', video_settings.get('preset', 'medium')])
                cmd.extend(['-crf', str(video_settings.get('crf', 23))])
                if video_settings.get('bitrate'):
                    cmd.extend(['-b:v', video_settings['bitrate']])
        
        # 音频设置
        if audio_settings:
            if audio_settings.get('keep_original'):
                cmd.extend(['-c:a', 'aac', '-b:a', '128k'])
                if audio_settings.get('volume', 100) != 100:
                    volume = audio_settings['volume'] / 100.0
                    cmd.extend(['-af', f'volume={volume}'])
            else:
                cmd.extend(['-an'])  # 无音频
        
        # 视频设置
        if video_settings:
            if video_settings.get('resolution'):
                cmd.extend(['-s', video_settings['resolution']])
            if video_settings.get('fps'):
                cmd.extend(['-r', str(video_settings['fps'])])
        
        # 其他设置
        cmd.extend([
            '-movflags', '+faststart',
            '-pix_fmt', 'yuv420p'
        ])
        
        cmd.append(output_path)
        
        return cmd
    
    @staticmethod
    def create_concat_file(video_files: List[str], input_folder: str) -> str:
        """
        创建FFmpeg concat文件
        
        Args:
            video_files: 视频文件名列表
            input_folder: 输入文件夹路径
            
        Returns:
            str: 临时concat文件路径
        """
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', 
                                       delete=False, encoding='utf-8') as f:
            for file in video_files:
                file_path = os.path.join(input_folder, file).replace('\\', '/')
                f.write(f"file '{file_path}'\n")
            return f.name
