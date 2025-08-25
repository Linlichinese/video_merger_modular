"""
批处理器模块

管理多个文件夹的并发视频处理，支持暂停、恢复、取消等操作
"""

import os
import time
import threading
from typing import Dict, List, Optional, Callable
from queue import Queue, Empty
from concurrent.futures import ThreadPoolExecutor, Future
from functools import partial
from PyQt5.QtCore import QObject, pyqtSignal, QTimer, Qt
from PyQt5.QtWidgets import QMessageBox

from .video_processor import VideoProcessor
from .video_splitter import VideoSplitter
from .ffmpeg_processor import FFmpegGPUProcessor
from .task_manager import TaskManager, TaskStatus, FailureReason


class BatchJobType:
    """批处理任务类型"""
    MERGE = "merge"      # 视频合成
    SPLIT = "split"      # 视频分割


class BatchJobInfo:
    """批处理任务信息"""
    def __init__(self, folder_path: str, job_type: str, settings: dict):
        self.folder_path = folder_path
        self.job_type = job_type  # MERGE 或 SPLIT
        self.settings = settings  # 处理设置
        self.status = "pending"   # pending, processing, completed, failed, paused, cancelled
        self.progress = 0.0
        self.processor = None     # VideoProcessor 或 VideoSplitter 实例
        self.future = None        # Future 对象
        self.error_message = ""
        self.start_time = None
        self.end_time = None
        self.paused = False


class BatchProcessor(QObject):
    """批处理器 - 管理多个文件夹的并发处理"""
    
    # 信号定义
    job_started = pyqtSignal(str)           # 任务开始 (folder_path)
    job_progress = pyqtSignal(str, float)   # 任务进度 (folder_path, progress)
    job_completed = pyqtSignal(str, str)    # 任务完成 (folder_path, message)
    job_failed = pyqtSignal(str, str)       # 任务失败 (folder_path, error_message)
    job_paused = pyqtSignal(str)            # 任务暂停 (folder_path)
    job_resumed = pyqtSignal(str)           # 任务恢复 (folder_path)
    job_cancelled = pyqtSignal(str)         # 任务取消 (folder_path)
    
    batch_started = pyqtSignal()            # 批处理开始
    batch_completed = pyqtSignal()          # 批处理完成
    batch_paused = pyqtSignal()             # 批处理暂停
    batch_resumed = pyqtSignal()            # 批处理恢复
    batch_cancelled = pyqtSignal()          # 批处理取消
    
    overall_progress = pyqtSignal(float)    # 整体进度 (0.0-1.0)
    
    def __init__(self, max_concurrent_jobs: int = 2, parent=None):
        super().__init__(parent)
        self.max_concurrent_jobs = max_concurrent_jobs
        self.jobs: Dict[str, BatchJobInfo] = {}  # folder_path -> BatchJobInfo
        self.running = False
        self.paused = False
        self.cancelled = False
        
        # 线程池执行器
        self.executor = ThreadPoolExecutor(max_workers=max_concurrent_jobs)
        
        # 任务队列
        self.pending_jobs = Queue()
        
        # 线程安全锁
        self._lock = threading.RLock()
        
        # 进度更新定时器
        self.progress_timer = QTimer()
        self.progress_timer.timeout.connect(self._update_overall_progress)
        self.progress_timer.setInterval(1000)  # 每秒更新一次
        
        # GPU配置管理器（从主窗口获取）
        self.gpu_config_manager = None
    
    def set_gpu_config_manager(self, gpu_config_manager):
        """设置GPU配置管理器"""
        self.gpu_config_manager = gpu_config_manager
    
    def add_merge_job(self, folder_path: str, output_folder: str, videos_per_output: int, 
                     total_outputs: int, resolution: str, bitrate: str, reuse_material: bool, 
                     audio_settings: dict, use_gpu: bool = False, quality: str = "high"):
        """添加视频合成任务"""
        if folder_path in self.jobs:
            return False  # 任务已存在
        
        settings = {
            'output_folder': output_folder,
            'videos_per_output': videos_per_output,
            'total_outputs': total_outputs,
            'resolution': resolution,
            'bitrate': bitrate,
            'reuse_material': reuse_material,
            'audio_settings': audio_settings,
            'use_gpu': use_gpu,
            'quality': quality
        }
        
        job = BatchJobInfo(folder_path, BatchJobType.MERGE, settings)
        
        with self._lock:
            self.jobs[folder_path] = job
            self.pending_jobs.put(job)
        
        return True
    
    def add_split_job(self, folder_path: str, output_folder: str, duration_range: tuple,
                     resolution: str = None, bitrate: str = None, use_gpu: bool = False, 
                     quality: str = "medium", save_metadata: bool = True, delete_original: bool = False):
        """添加视频分割任务"""
        if folder_path in self.jobs:
            return False  # 任务已存在
        
        settings = {
            'output_folder': output_folder,
            'duration_range': duration_range,
            'resolution': resolution,
            'bitrate': bitrate,
            'use_gpu': use_gpu,
            'quality': quality,
            'save_metadata': save_metadata,
            'delete_original': delete_original
        }
        
        job = BatchJobInfo(folder_path, BatchJobType.SPLIT, settings)
        
        with self._lock:
            self.jobs[folder_path] = job
            self.pending_jobs.put(job)
        
        return True
    
    def start_batch(self):
        """开始批处理"""
        with self._lock:
            if self.running:
                return False
            
            if not self.jobs:
                return False
            
            self.running = True
            self.paused = False
            self.cancelled = False
        
        self.batch_started.emit()
        self.progress_timer.start()
        
        # 启动处理线程
        self._start_processing_thread()
        return True
    
    def pause_batch(self):
        """暂停批处理"""
        with self._lock:
            if not self.running or self.paused:
                return False
            
            self.paused = True
        
        # 暂停所有正在运行的任务
        for job in self.jobs.values():
            if job.status == "processing" and job.processor:
                job.paused = True
                if hasattr(job.processor, 'pause'):
                    job.processor.pause()
                job.status = "paused"
                self.job_paused.emit(job.folder_path)
        
        self.batch_paused.emit()
        return True
    
    def resume_batch(self):
        """恢复批处理"""
        with self._lock:
            if not self.running or not self.paused:
                return False
            
            self.paused = False
        
        # 恢复所有暂停的任务
        for job in self.jobs.values():
            if job.status == "paused" and job.processor:
                job.paused = False
                if hasattr(job.processor, 'resume'):
                    job.processor.resume()
                job.status = "processing"
                self.job_resumed.emit(job.folder_path)
        
        self.batch_resumed.emit()
        return True
    
    def cancel_batch(self):
        """取消批处理"""
        with self._lock:
            if not self.running:
                return False
            
            self.cancelled = True
            self.running = False
            self.paused = False
        
        # 取消所有任务
        for job in self.jobs.values():
            if job.status in ["pending", "processing", "paused"]:
                self._cancel_job(job)
        
        # 清空待处理队列
        while not self.pending_jobs.empty():
            try:
                self.pending_jobs.get_nowait()
            except Empty:
                break
        
        self.progress_timer.stop()
        self.batch_cancelled.emit()
        return True
    
    def remove_job(self, folder_path: str):
        """移除指定任务"""
        with self._lock:
            if folder_path not in self.jobs:
                return False
            
            job = self.jobs[folder_path]
            
            # 如果任务正在运行，先取消
            if job.status in ["processing", "paused"]:
                self._cancel_job(job)
            
            # 移除任务
            del self.jobs[folder_path]
        
        return True
    
    def pause_job(self, folder_path: str):
        """暂停指定任务"""
        with self._lock:
            if folder_path not in self.jobs:
                return False
            
            job = self.jobs[folder_path]
            if job.status != "processing":
                return False
            
            job.paused = True
            if job.processor and hasattr(job.processor, 'pause'):
                job.processor.pause()
            job.status = "paused"
            self.job_paused.emit(folder_path)
        
        return True
    
    def resume_job(self, folder_path: str):
        """恢复指定任务"""
        with self._lock:
            if folder_path not in self.jobs:
                return False
            
            job = self.jobs[folder_path]
            if job.status != "paused":
                return False
            
            job.paused = False
            if job.processor and hasattr(job.processor, 'resume'):
                job.processor.resume()
            job.status = "processing"
            self.job_resumed.emit(folder_path)
        
        return True
    
    def get_job_status(self, folder_path: str) -> Optional[str]:
        """获取任务状态"""
        job = self.jobs.get(folder_path)
        return job.status if job else None
    
    def get_job_progress(self, folder_path: str) -> float:
        """获取任务进度"""
        job = self.jobs.get(folder_path)
        return job.progress if job else 0.0
    
    def get_overall_progress(self) -> float:
        """获取整体进度"""
        if not self.jobs:
            return 0.0
        
        total_progress = sum(job.progress for job in self.jobs.values())
        return total_progress / len(self.jobs)
    
    def get_statistics(self) -> dict:
        """获取统计信息"""
        with self._lock:
            stats = {
                'total': len(self.jobs),
                'pending': len([j for j in self.jobs.values() if j.status == "pending"]),
                'processing': len([j for j in self.jobs.values() if j.status == "processing"]),
                'completed': len([j for j in self.jobs.values() if j.status == "completed"]),
                'failed': len([j for j in self.jobs.values() if j.status == "failed"]),
                'paused': len([j for j in self.jobs.values() if j.status == "paused"]),
                'cancelled': len([j for j in self.jobs.values() if j.status == "cancelled"]),
                'running': self.running,
                'paused': self.paused,
                'overall_progress': self.get_overall_progress()
            }
        
        return stats
    
    def _start_processing_thread(self):
        """启动处理线程"""
        def process_jobs():
            while self.running and not self.cancelled:
                if self.paused:
                    time.sleep(1)
                    continue
                
                try:
                    # 获取待处理任务
                    job = self.pending_jobs.get(timeout=1)
                    
                    if self.cancelled:
                        break
                    
                    # 提交任务到线程池
                    future = self.executor.submit(self._process_job, job)
                    job.future = future
                    
                except Empty:
                    # 检查是否所有任务都完成了
                    active_jobs = [j for j in self.jobs.values() 
                                  if j.status in ["pending", "processing", "paused"]]
                    if not active_jobs:
                        break
                    continue
                except Exception as e:
                    print(f"处理线程错误: {e}")
                    break
            
            # 批处理完成
            if not self.cancelled:
                self.running = False
                self.progress_timer.stop()
                self.batch_completed.emit()
        
        thread = threading.Thread(target=process_jobs, daemon=True)
        thread.start()
    
    def _process_job(self, job: BatchJobInfo):
        """处理单个任务"""
        try:
            job.status = "processing"
            job.start_time = time.time()
            self.job_started.emit(job.folder_path)
            
            # 创建处理器
            if job.job_type == BatchJobType.MERGE:
                processor = self._create_merge_processor(job)
            else:  # SPLIT
                processor = self._create_split_processor(job)
            
            job.processor = processor
            
            # 连接信号（使用队列连接确保线程安全）
            # 使用partial避免lambda闭包问题
            processor.progress_updated.connect(
                partial(self._on_job_progress, job.folder_path),
                Qt.QueuedConnection
            )
            processor.process_finished.connect(
                partial(self._on_job_finished, job.folder_path),
                Qt.QueuedConnection
            )
            
            # 如果支持详细进度信号，也连接它
            if hasattr(processor, 'detailed_progress_updated'):
                processor.detailed_progress_updated.connect(
                    partial(self._on_job_detailed_progress, job.folder_path),
                    Qt.QueuedConnection
                )
            
            # 启动处理
            processor.start()
            
            # 等待完成
            processor.wait()
            
        except Exception as e:
            job.status = "failed"
            job.error_message = str(e)
            job.end_time = time.time()
            self.job_failed.emit(job.folder_path, str(e))
    
    def _create_merge_processor(self, job: BatchJobInfo) -> VideoProcessor:
        """创建视频合成处理器"""
        settings = job.settings
        audio_settings = settings['audio_settings']
        
        # 检查是否有复杂音频处理需求
        has_replace_audio = (audio_settings.get('replace_audio', False) and 
                           audio_settings.get('replace_audio_path', ''))
        has_background_audio = (audio_settings.get('background_audio', False) and 
                              audio_settings.get('background_audio_path', ''))
        needs_complex_audio = has_replace_audio or has_background_audio
        
        # 根据GPU设置和音频需求选择处理器类型
        if (settings.get('use_gpu', False) and 
            self.gpu_config_manager and 
            self.gpu_config_manager.gpu_info['use_gpu'] and 
            not needs_complex_audio):
            # 使用GPU加速处理器（仅当没有复杂音频需求时）
            gpu_settings = self.gpu_config_manager.gpu_info.copy()
            gpu_settings['quality'] = settings.get('quality', 'high')
            
            print(f"[BatchProcessor] 使用GPU处理器（无复杂音频需求）")
            processor = FFmpegGPUProcessor(
                job.folder_path,
                settings['output_folder'],
                settings['videos_per_output'],
                settings['total_outputs'],
                settings['resolution'],
                settings['bitrate'],
                settings['reuse_material'],
                settings['audio_settings'],
                gpu_settings
            )
        else:
            # 使用传统处理器（支持复杂音频处理）
            if needs_complex_audio:
                print(f"[BatchProcessor] 检测到复杂音频需求，使用VideoProcessor")
                print(f"[BatchProcessor] 替换音频: {has_replace_audio}, 背景音频: {has_background_audio}")
            else:
                print(f"[BatchProcessor] 使用VideoProcessor（GPU未启用或不可用）")
                
            processor = VideoProcessor(
                job.folder_path,
                settings['output_folder'],
                settings['videos_per_output'],
                settings['total_outputs'],
                settings['resolution'],
                settings['bitrate'],
                settings['reuse_material'],
                settings['audio_settings']
            )
        
        return processor
    
    def _create_split_processor(self, job: BatchJobInfo) -> VideoSplitter:
        """创建视频分割处理器"""
        settings = job.settings
        
        # 强制使用GPU加速进行分割
        use_gpu = True  # 强制GPU分割
        
        processor = VideoSplitter(
            job.folder_path,
            settings['output_folder'],
            settings['duration_range'],
            settings.get('resolution'),
            settings.get('bitrate'),
            use_gpu,  # 强制使用GPU
            settings.get('quality', 'medium'),
            settings.get('save_metadata', True),
            settings.get('delete_original', False)
        )
        
        return processor
    
    def _cancel_job(self, job: BatchJobInfo):
        """取消指定任务"""
        if job.processor and job.processor.isRunning():
            job.processor.stop()
        
        job.status = "cancelled"
        job.end_time = time.time()
        self.job_cancelled.emit(job.folder_path)
    
    def _on_job_progress(self, folder_path: str, progress: int):
        """任务进度更新回调"""
        with self._lock:
            job = self.jobs.get(folder_path)
            if job:
                # 转换进度并更新任务状态
                new_progress = progress / 100.0  # 转换为0.0-1.0
                job.progress = new_progress
                
                # 发射任务进度信号
                self.job_progress.emit(folder_path, job.progress)
                
                # 立即更新整体进度
                self._update_overall_progress_immediate()
    
    def _on_job_detailed_progress(self, folder_path: str, progress: float):
        """任务详细进度更新回调（浮点值0.0-1.0）"""
        with self._lock:
            job = self.jobs.get(folder_path)
            if job:
                # 直接使用浮点进度值
                job.progress = progress
                
                # 发射任务进度信号
                self.job_progress.emit(folder_path, job.progress)
                
                # 立即更新整体进度
                self._update_overall_progress_immediate()
    
    def _on_job_finished(self, folder_path: str, message: str):
        """任务完成回调"""
        with self._lock:
            job = self.jobs.get(folder_path)
            if job:
                print(f"[BatchProcessor] 任务完成回调: {folder_path}, 消息: {message}")
                if "完成" in message:
                    job.status = "completed"
                    job.progress = 1.0
                    self.job_completed.emit(folder_path, message)
                    print(f"[BatchProcessor] 任务标记为完成: {folder_path}")
                else:
                    job.status = "failed"
                    job.error_message = message
                    self.job_failed.emit(folder_path, message)
                    print(f"[BatchProcessor] 任务标记为失败: {folder_path}")
                
                job.end_time = time.time()
                
                # 检查是否所有任务都完成了
                self._check_batch_completion()
    
    def _update_overall_progress(self):
        """更新整体进度"""
        self.overall_progress.emit(self.get_overall_progress())
    
    def _update_overall_progress_immediate(self):
        """立即更新整体进度（无定时器延迟）"""
        overall_progress = self.get_overall_progress()
        self.overall_progress.emit(overall_progress)
    
    def _check_batch_completion(self):
        """检查批处理是否完成"""
        if not self.running:
            return
            
        # 检查是否所有任务都完成了（completed, failed, 或 cancelled）
        active_jobs = [j for j in self.jobs.values() 
                      if j.status in ["pending", "processing", "paused"]]
        
        print(f"[BatchProcessor] 检查批处理完成状态:")
        print(f"  总任务数: {len(self.jobs)}")
        print(f"  活跃任务数: {len(active_jobs)}")
        for job_path, job in self.jobs.items():
            print(f"  {os.path.basename(job_path)}: {job.status}")
        
        if not active_jobs:
            print(f"[BatchProcessor] 所有任务都已完成，发射批处理完成信号")
            # 防重复机制：确保只发射一次完成信号
            if self.running:  # 再次检查避免竞态条件
                self.running = False
                self.progress_timer.stop()
                self.batch_completed.emit()
                print(f"[BatchProcessor] 批处理完成信号已发射")
    
    def cleanup(self):
        """清理资源"""
        self.cancel_batch()
        
        # 等待所有任务完成
        for job in self.jobs.values():
            if job.future and not job.future.done():
                job.future.cancel()
        
        # 关闭线程池
        self.executor.shutdown(wait=True)
        
        # 停止定时器
        self.progress_timer.stop()
