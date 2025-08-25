"""
强健的视频处理器模块

集成断点续传、失败重试、资源清理等高级功能
"""

import os
import time
import psutil
import tempfile
from typing import Optional, List, Dict, Any
from PyQt5.QtCore import QThread, pyqtSignal

from .task_manager import TaskManager, TaskInfo, RobustTaskExecutor, FailureReason
from .video_processor import VideoProcessor
from .ffmpeg_processor import FFmpegGPUProcessor
from .process_controller import ProcessController


class RobustVideoProcessor(QThread):
    """强健的视频处理器 - 支持断点续传和失败重试"""
    
    # 信号定义
    progress_updated = pyqtSignal(int)
    process_finished = pyqtSignal(str)
    detailed_progress_updated = pyqtSignal(float)
    task_status_changed = pyqtSignal(str, str)  # task_id, status
    job_statistics_updated = pyqtSignal(dict)
    resume_available = pyqtSignal(str)  # job_id
    
    def __init__(self, input_folder: str, output_folder: str, videos_per_output: int, 
                 total_outputs: int, resolution: str, bitrate: str, 
                 reuse_material: bool, audio_settings: Dict, gpu_settings: Dict = None):
        super().__init__()
        
        # 基础参数
        self.input_folder = input_folder
        self.output_folder = output_folder
        self.videos_per_output = videos_per_output
        self.total_outputs = total_outputs
        self.resolution = resolution
        self.bitrate = bitrate
        self.reuse_material = reuse_material
        self.audio_settings = audio_settings
        self.gpu_settings = gpu_settings or {}
        
        # 任务管理
        self.task_manager = TaskManager()
        self.task_executor = RobustTaskExecutor(self.task_manager)
        
        # 处理器选择
        self.use_gpu = gpu_settings and gpu_settings.get('use_gpu', False)
        
        # 控制变量
        self.running = True
        self._cancel_requested = False
        self._paused = False
        
        # 资源管理
        self.resource_monitor = ResourceMonitor()
        self.temp_file_manager = TempFileManager()
        
        # 统计信息
        self._last_stats_update = 0
        self._stats_update_interval = 2.0  # 2秒更新一次统计
    
    def create_new_job(self) -> str:
        """创建新的批处理任务"""
        try:
            job_id = self.task_manager.create_batch_job(
                input_folder=self.input_folder,
                output_folder=self.output_folder,
                videos_per_output=self.videos_per_output,
                total_outputs=self.total_outputs,
                resolution=self.resolution,
                bitrate=self.bitrate,
                audio_settings=self.audio_settings,
                gpu_settings=self.gpu_settings,
                reuse_material=self.reuse_material
            )
            return job_id
        except Exception as e:
            self.process_finished.emit(f"创建任务失败: {str(e)}")
            return ""
    
    def resume_job(self, job_id: str) -> bool:
        """恢复已存在的任务"""
        success = self.task_manager.load_job(job_id)
        if success:
            self.resume_available.emit(job_id)
        return success
    
    def run(self):
        """主处理循环"""
        try:
            # 检查是否有可恢复的任务
            resumable_tasks = self.task_manager.get_resumable_tasks()
            
            if not resumable_tasks:
                self.process_finished.emit("没有可处理的任务")
                return
            
            self.process_finished.emit(f"开始处理 {len(resumable_tasks)} 个任务")
            
            # 处理所有任务
            for task in resumable_tasks:
                if not self.running or self._cancel_requested:
                    break
                
                # 检查暂停状态
                while self._paused and self.running and not self._cancel_requested:
                    time.sleep(0.1)
                
                if not self.running or self._cancel_requested:
                    break
                
                # 资源检查
                if not self._check_resources(task):
                    self._wait_for_resources()
                    continue
                
                # 执行任务
                self._execute_single_task(task)
                
                # 更新统计信息
                self._update_statistics()
                
                # 自动保存状态
                self.task_manager.save_state()
            
            # 处理完成
            self._handle_completion()
            
        except Exception as e:
            self.process_finished.emit(f"处理过程中发生错误: {str(e)}")
        finally:
            self._cleanup_resources()
    
    def _execute_single_task(self, task: TaskInfo):
        """执行单个任务"""
        try:
            # 发射任务状态变化信号
            self.task_status_changed.emit(task.task_id, "running")
            
            # 创建处理器
            if self.use_gpu:
                processor = self._create_gpu_processor(task)
            else:
                processor = self._create_cpu_processor(task)
            
            # 执行任务
            def process_task(task_info: TaskInfo) -> bool:
                try:
                    return self._process_with_monitoring(processor, task_info)
                except Exception as e:
                    # 记录详细错误信息
                    error_details = self._analyze_error(e, task_info)
                    raise Exception(error_details)
            
            success = self.task_executor.execute_task(task, process_task)
            
            if success:
                self.task_status_changed.emit(task.task_id, "completed")
            else:
                self.task_status_changed.emit(task.task_id, "failed")
                
        except Exception as e:
            self.process_finished.emit(f"任务 {task.task_id} 执行失败: {str(e)}")
    
    def _create_gpu_processor(self, task: TaskInfo) -> FFmpegGPUProcessor:
        """创建GPU处理器"""
        return FFmpegGPUProcessor(
            input_folder=self.input_folder,
            output_folder=os.path.dirname(task.output_path),
            videos_per_output=len(task.input_files),
            total_outputs=1,  # 单个任务
            resolution=self.resolution,
            bitrate=self.bitrate,
            reuse_material=self.reuse_material,
            audio_settings=self.audio_settings,
            gpu_settings=self.gpu_settings
        )
    
    def _create_cpu_processor(self, task: TaskInfo) -> VideoProcessor:
        """创建CPU处理器"""
        return VideoProcessor(
            input_folder=self.input_folder,
            output_folder=os.path.dirname(task.output_path),
            videos_per_output=len(task.input_files),
            total_outputs=1,  # 单个任务
            resolution=self.resolution,
            bitrate=self.bitrate,
            reuse_material=self.reuse_material,
            audio_settings=self.audio_settings
        )
    
    def _process_with_monitoring(self, processor, task: TaskInfo) -> bool:
        """带监控的处理执行"""
        # 连接进度信号
        processor.detailed_progress_updated.connect(
            lambda progress: self._on_task_progress(task.task_id, progress)
        )
        
        # 执行处理
        try:
            # 这里需要根据具体处理器调整
            if hasattr(processor, 'process_and_merge'):
                processor.process_and_merge(task.input_files, task.output_number)
            else:
                processor.run()
            
            # 检查输出文件
            return self._verify_output(task.output_path)
            
        except Exception as e:
            # 清理不完整的输出文件
            self._cleanup_incomplete_output(task.output_path)
            raise e
    
    def _verify_output(self, output_path: str) -> bool:
        """验证输出文件的完整性"""
        if not os.path.exists(output_path):
            return False
        
        # 检查文件大小
        file_size = os.path.getsize(output_path)
        if file_size < 1024:  # 小于1KB认为是无效文件
            return False
        
        # 可以添加更多验证逻辑，如使用ffprobe检查文件完整性
        return True
    
    def _cleanup_incomplete_output(self, output_path: str):
        """清理不完整的输出文件"""
        try:
            if os.path.exists(output_path):
                os.unlink(output_path)
        except Exception:
            pass  # 忽略清理错误
    
    def _check_resources(self, task: TaskInfo) -> bool:
        """检查系统资源是否足够"""
        return self.resource_monitor.check_resources_for_task(task)
    
    def _wait_for_resources(self):
        """等待资源可用"""
        wait_time = 10  # 等待10秒
        self.process_finished.emit(f"资源不足，等待 {wait_time} 秒后重试...")
        
        for i in range(wait_time):
            if not self.running or self._cancel_requested:
                break
            time.sleep(1)
    
    def _on_task_progress(self, task_id: str, progress: float):
        """处理任务进度更新"""
        self.task_manager.update_task_progress(task_id, progress)
        
        # 计算整体进度
        stats = self.task_manager.get_job_statistics()
        overall_progress = stats.get('overall_progress', 0.0)
        
        self.detailed_progress_updated.emit(overall_progress)
        self.progress_updated.emit(int(overall_progress * 100))
    
    def _update_statistics(self):
        """更新统计信息"""
        current_time = time.time()
        if current_time - self._last_stats_update >= self._stats_update_interval:
            stats = self.task_manager.get_job_statistics()
            self.job_statistics_updated.emit(stats)
            self._last_stats_update = current_time
    
    def _analyze_error(self, error: Exception, task: TaskInfo) -> str:
        """分析错误并提供详细信息"""
        error_msg = str(error)
        
        # 添加上下文信息
        context = {
            'task_id': task.task_id,
            'input_files': task.input_files,
            'output_path': task.output_path,
            'retry_count': task.retry_count,
            'system_info': {
                'memory_usage': psutil.virtual_memory().percent,
                'disk_usage': psutil.disk_usage(os.path.dirname(task.output_path)).percent,
                'cpu_usage': psutil.cpu_percent()
            }
        }
        
        return f"{error_msg}\n上下文信息: {context}"
    
    def _handle_completion(self):
        """处理任务完成"""
        stats = self.task_manager.get_job_statistics()
        
        if stats['failed'] == 0:
            self.process_finished.emit("所有任务处理完成！")
        else:
            completed = stats['completed']
            failed = stats['failed']
            self.process_finished.emit(f"处理完成：成功 {completed} 个，失败 {failed} 个")
    
    def _cleanup_resources(self):
        """清理资源"""
        try:
            # 清理临时文件
            self.temp_file_manager.cleanup_all()
            
            # 保存最终状态
            self.task_manager.save_state()
            
        except Exception as e:
            print(f"资源清理失败: {e}")
    
    def pause(self):
        """暂停处理"""
        self._paused = True
    
    def resume(self):
        """恢复处理"""
        self._paused = False
    
    def stop(self):
        """停止处理"""
        self.running = False
        self._cancel_requested = True
        self.wait()
    
    def get_resumable_jobs(self) -> List[str]:
        """获取可恢复的任务列表"""
        persistence_dir = self.task_manager.persistence_dir
        jobs = []
        
        for filename in os.listdir(persistence_dir):
            if filename.endswith('.json') and filename.startswith('job_'):
                job_id = filename[:-5]  # 移除.json后缀
                jobs.append(job_id)
        
        return jobs


class ResourceMonitor:
    """系统资源监控器"""
    
    def __init__(self):
        self.memory_threshold = 85  # 内存使用率阈值
        self.disk_threshold = 90    # 磁盘使用率阈值
        self.cpu_threshold = 95     # CPU使用率阈值
    
    def check_resources_for_task(self, task: TaskInfo) -> bool:
        """检查任务执行所需的系统资源"""
        try:
            # 检查内存使用率
            memory = psutil.virtual_memory()
            if memory.percent > self.memory_threshold:
                return False
            
            # 检查磁盘空间
            disk = psutil.disk_usage(os.path.dirname(task.output_path))
            if disk.percent > self.disk_threshold:
                return False
            
            # 检查CPU使用率
            cpu_percent = psutil.cpu_percent(interval=1)
            if cpu_percent > self.cpu_threshold:
                return False
            
            return True
            
        except Exception:
            # 如果无法检查资源，假设可用
            return True
    
    def get_resource_status(self) -> Dict:
        """获取当前资源状态"""
        try:
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            cpu_percent = psutil.cpu_percent()
            
            return {
                'memory_percent': memory.percent,
                'memory_available_gb': memory.available / (1024**3),
                'disk_percent': disk.percent,
                'disk_free_gb': disk.free / (1024**3),
                'cpu_percent': cpu_percent
            }
        except Exception:
            return {}


class TempFileManager:
    """临时文件管理器"""
    
    def __init__(self):
        self.temp_files: List[str] = []
        self.temp_dirs: List[str] = []
    
    def create_temp_file(self, suffix: str = '', prefix: str = 'videomerger_') -> str:
        """创建临时文件"""
        fd, path = tempfile.mkstemp(suffix=suffix, prefix=prefix)
        os.close(fd)
        self.temp_files.append(path)
        return path
    
    def create_temp_dir(self, prefix: str = 'videomerger_') -> str:
        """创建临时目录"""
        path = tempfile.mkdtemp(prefix=prefix)
        self.temp_dirs.append(path)
        return path
    
    def cleanup_all(self):
        """清理所有临时文件和目录"""
        # 清理临时文件
        for file_path in self.temp_files[:]:
            try:
                if os.path.exists(file_path):
                    os.unlink(file_path)
                self.temp_files.remove(file_path)
            except Exception:
                pass  # 忽略清理错误
        
        # 清理临时目录
        for dir_path in self.temp_dirs[:]:
            try:
                if os.path.exists(dir_path):
                    import shutil
                    shutil.rmtree(dir_path)
                self.temp_dirs.remove(dir_path)
            except Exception:
                pass  # 忽略清理错误
