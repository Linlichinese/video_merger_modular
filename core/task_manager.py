"""
任务管理器模块

提供断点续传、失败重试、状态持久化等高级任务管理功能
"""

import os
import json
import time
import threading
from enum import Enum
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta


def generate_unique_filename_for_task(output_folder: str, base_name: str, extension: str = "mp4") -> str:
    """
    为任务管理器生成唯一的文件名，避免覆盖现有文件
    
    Args:
        output_folder: 输出文件夹路径
        base_name: 基础文件名（不含扩展名）
        extension: 文件扩展名
    
    Returns:
        str: 完整的文件路径
    """
    # 添加时间戳到基础文件名
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    counter = 1
    while True:
        if counter == 1:
            # 第一次尝试：基础名_时间戳_序号
            filename = f"{base_name}_{timestamp}_{counter:03d}.{extension}"
        else:
            # 后续尝试：基础名_时间戳_序号
            filename = f"{base_name}_{timestamp}_{counter:03d}.{extension}"
        
        full_path = os.path.join(output_folder, filename)
        
        if not os.path.exists(full_path):
            return full_path
        
        counter += 1
        
        # 防止无限循环，最多尝试999次
        if counter > 999:
            # 如果还是冲突，使用微秒级时间戳
            microsecond_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            filename = f"{base_name}_{microsecond_timestamp}.{extension}"
            return os.path.join(output_folder, filename)


class TaskStatus(Enum):
    """任务状态枚举"""
    PENDING = "pending"          # 待处理
    RUNNING = "running"          # 正在处理
    COMPLETED = "completed"      # 已完成
    FAILED = "failed"           # 失败
    CANCELLED = "cancelled"      # 已取消
    RETRYING = "retrying"       # 重试中


class FailureReason(Enum):
    """失败原因枚举"""
    UNKNOWN = "unknown"
    FILE_NOT_FOUND = "file_not_found"
    INSUFFICIENT_MEMORY = "insufficient_memory"
    DISK_FULL = "disk_full"
    PERMISSION_DENIED = "permission_denied"
    FFMPEG_ERROR = "ffmpeg_error"
    TIMEOUT = "timeout"
    CORRUPTION = "corruption"


@dataclass
class TaskInfo:
    """单个任务信息"""
    task_id: str
    input_files: List[str]
    output_path: str
    output_number: int
    status: TaskStatus = TaskStatus.PENDING
    progress: float = 0.0
    created_time: str = ""
    started_time: Optional[str] = None
    completed_time: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    failure_reason: Optional[FailureReason] = None
    error_message: str = ""
    estimated_duration: float = 0.0
    actual_duration: float = 0.0
    
    def __post_init__(self):
        if not self.created_time:
            self.created_time = datetime.now().isoformat()


@dataclass 
class BatchJobInfo:
    """批处理任务信息"""
    job_id: str
    input_folder: str
    output_folder: str
    videos_per_output: int
    total_outputs: int
    resolution: str
    bitrate: str
    audio_settings: Dict
    gpu_settings: Dict
    reuse_material: bool
    created_time: str = ""
    started_time: Optional[str] = None
    completed_time: Optional[str] = None
    status: TaskStatus = TaskStatus.PENDING
    completed_tasks: int = 0
    failed_tasks: int = 0
    total_progress: float = 0.0
    
    def __post_init__(self):
        if not self.created_time:
            self.created_time = datetime.now().isoformat()


class TaskManager:
    """任务管理器 - 支持断点续传和失败重试"""
    
    def __init__(self, persistence_dir: str = None):
        self.persistence_dir = persistence_dir or os.path.join(os.getcwd(), '.video_merger', 'tasks')
        os.makedirs(self.persistence_dir, exist_ok=True)
        
        self.current_job: Optional[BatchJobInfo] = None
        self.tasks: Dict[str, TaskInfo] = {}
        self.task_callbacks: Dict[str, Callable] = {}
        
        # 重试配置
        self.retry_delays = [1, 2, 4, 8, 16]  # 指数退避延迟（秒）
        self.max_concurrent_retries = 2
        
        # 线程安全
        self._lock = threading.RLock()
        
        # 自动保存定时器
        self._auto_save_timer = threading.Timer(30.0, self._auto_save)
        self._auto_save_timer.daemon = True
        self._auto_save_timer.start()
    
    def create_batch_job(self, input_folder: str, output_folder: str, 
                        videos_per_output: int, total_outputs: int,
                        resolution: str, bitrate: str, 
                        audio_settings: Dict, gpu_settings: Dict,
                        reuse_material: bool) -> str:
        """创建批处理任务"""
        with self._lock:
            job_id = f"job_{int(time.time())}_{hash(input_folder) % 10000}"
            
            self.current_job = BatchJobInfo(
                job_id=job_id,
                input_folder=input_folder,
                output_folder=output_folder,
                videos_per_output=videos_per_output,
                total_outputs=total_outputs,
                resolution=resolution,
                bitrate=bitrate,
                audio_settings=audio_settings,
                gpu_settings=gpu_settings,
                reuse_material=reuse_material
            )
            
            # 生成所有子任务
            self._generate_tasks()
            
            # 保存状态
            self.save_state()
            
            return job_id
    
    def _generate_tasks(self):
        """生成所有子任务"""
        if not self.current_job:
            return
            
        # 清空现有任务
        self.tasks.clear()
        
        # 获取视频文件列表
        video_extensions = ('.mp4', '.avi', '.mov', '.mkv', '.flv', '.wmv', '.mpeg', '.mpg')
        video_files = [f for f in os.listdir(self.current_job.input_folder) 
                      if f.lower().endswith(video_extensions)]
        
        if not video_files:
            raise ValueError("输入文件夹中没有找到视频文件")
        
        # 生成任务
        for i in range(self.current_job.total_outputs):
            task_id = f"{self.current_job.job_id}_task_{i+1:04d}"
            # 使用智能命名避免覆盖现有文件
            output_path = generate_unique_filename_for_task(self.current_job.output_folder, f"merged_{i+1:03d}", "mp4")
            
            # 这里简化处理，实际应该使用SequenceDiversitySelector
            selected_files = video_files[:self.current_job.videos_per_output]
            
            task = TaskInfo(
                task_id=task_id,
                input_files=selected_files,
                output_path=output_path,
                output_number=i+1,
                max_retries=3
            )
            
            self.tasks[task_id] = task
    
    def load_job(self, job_id: str) -> bool:
        """加载已存在的批处理任务"""
        job_file = os.path.join(self.persistence_dir, f"{job_id}.json")
        if not os.path.exists(job_file):
            return False
            
        try:
            with open(job_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 恢复任务信息
            self.current_job = BatchJobInfo(**data['job'])
            
            # 恢复任务列表
            self.tasks = {}
            for task_data in data['tasks']:
                task = TaskInfo(**task_data)
                task.status = TaskStatus(task.status)
                if task.failure_reason:
                    task.failure_reason = FailureReason(task.failure_reason)
                self.tasks[task.task_id] = task
            
            return True
            
        except Exception as e:
            print(f"加载任务失败: {e}")
            return False
    
    def save_state(self):
        """保存当前状态到文件"""
        if not self.current_job:
            return
            
        job_file = os.path.join(self.persistence_dir, f"{self.current_job.job_id}.json")
        
        try:
            with self._lock:
                data = {
                    'job': asdict(self.current_job),
                    'tasks': [asdict(task) for task in self.tasks.values()],
                    'saved_time': datetime.now().isoformat()
                }
                
                # 处理枚举类型
                data['job']['status'] = data['job']['status'].value if isinstance(data['job']['status'], TaskStatus) else data['job']['status']
                
                for task_data in data['tasks']:
                    task_data['status'] = task_data['status'].value if isinstance(task_data['status'], TaskStatus) else task_data['status']
                    if task_data['failure_reason']:
                        task_data['failure_reason'] = task_data['failure_reason'].value if isinstance(task_data['failure_reason'], FailureReason) else task_data['failure_reason']
                
                with open(job_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                    
        except Exception as e:
            print(f"保存状态失败: {e}")
    
    def get_resumable_tasks(self) -> List[TaskInfo]:
        """获取可恢复的任务列表"""
        with self._lock:
            resumable = []
            for task in self.tasks.values():
                if task.status in [TaskStatus.PENDING, TaskStatus.FAILED]:
                    if task.status == TaskStatus.FAILED and task.retry_count >= task.max_retries:
                        continue  # 超过最大重试次数
                    resumable.append(task)
            return resumable
    
    def get_completed_tasks(self) -> List[TaskInfo]:
        """获取已完成的任务列表"""
        with self._lock:
            return [task for task in self.tasks.values() if task.status == TaskStatus.COMPLETED]
    
    def get_failed_tasks(self) -> List[TaskInfo]:
        """获取失败的任务列表"""
        with self._lock:
            return [task for task in self.tasks.values() 
                   if task.status == TaskStatus.FAILED and task.retry_count >= task.max_retries]
    
    def mark_task_started(self, task_id: str):
        """标记任务开始"""
        with self._lock:
            if task_id in self.tasks:
                self.tasks[task_id].status = TaskStatus.RUNNING
                self.tasks[task_id].started_time = datetime.now().isoformat()
                self._update_job_progress()
    
    def mark_task_completed(self, task_id: str, actual_duration: float = 0):
        """标记任务完成"""
        with self._lock:
            if task_id in self.tasks:
                task = self.tasks[task_id]
                task.status = TaskStatus.COMPLETED
                task.completed_time = datetime.now().isoformat()
                task.progress = 1.0
                task.actual_duration = actual_duration
                
                if self.current_job:
                    self.current_job.completed_tasks += 1
                
                self._update_job_progress()
    
    def mark_task_failed(self, task_id: str, error_message: str, 
                        failure_reason: FailureReason = FailureReason.UNKNOWN):
        """标记任务失败"""
        with self._lock:
            if task_id in self.tasks:
                task = self.tasks[task_id]
                task.status = TaskStatus.FAILED
                task.error_message = error_message
                task.failure_reason = failure_reason
                # 注意：重试计数在执行器中已经处理，这里不再增加
                
                if self.current_job:
                    self.current_job.failed_tasks += 1
                
                self._update_job_progress()
                
                # 如果还能重试，安排重试
                if task.retry_count < task.max_retries:
                    self._schedule_retry(task_id)
    
    def update_task_progress(self, task_id: str, progress: float):
        """更新任务进度"""
        with self._lock:
            if task_id in self.tasks:
                self.tasks[task_id].progress = max(0.0, min(1.0, progress))
                self._update_job_progress()
    
    def _update_job_progress(self):
        """更新整体任务进度"""
        if not self.current_job or not self.tasks:
            return
            
        total_progress = sum(task.progress for task in self.tasks.values())
        self.current_job.total_progress = total_progress / len(self.tasks)
        
        # 检查是否全部完成
        completed = sum(1 for task in self.tasks.values() if task.status == TaskStatus.COMPLETED)
        if completed == len(self.tasks):
            self.current_job.status = TaskStatus.COMPLETED
            self.current_job.completed_time = datetime.now().isoformat()
    
    def _schedule_retry(self, task_id: str):
        """安排任务重试"""
        if task_id not in self.tasks:
            return
            
        task = self.tasks[task_id]
        if task.retry_count >= task.max_retries:
            return
        
        # 计算延迟时间（指数退避）
        delay_index = min(task.retry_count - 1, len(self.retry_delays) - 1)
        delay = self.retry_delays[delay_index]
        
        def retry_task():
            time.sleep(delay)
            with self._lock:
                if task_id in self.tasks and self.tasks[task_id].status == TaskStatus.FAILED:
                    self.tasks[task_id].status = TaskStatus.PENDING
                    self.tasks[task_id].error_message = ""
        
        retry_thread = threading.Thread(target=retry_task, daemon=True)
        retry_thread.start()
    
    def _auto_save(self):
        """自动保存状态"""
        try:
            self.save_state()
        except Exception as e:
            print(f"自动保存失败: {e}")
        finally:
            # 重新安排下次自动保存
            self._auto_save_timer = threading.Timer(30.0, self._auto_save)
            self._auto_save_timer.daemon = True
            self._auto_save_timer.start()
    
    def get_job_statistics(self) -> Dict:
        """获取任务统计信息"""
        if not self.current_job or not self.tasks:
            return {}
        
        with self._lock:
            stats = {
                'total_tasks': len(self.tasks),
                'completed': sum(1 for t in self.tasks.values() if t.status == TaskStatus.COMPLETED),
                'failed': sum(1 for t in self.tasks.values() if t.status == TaskStatus.FAILED),
                'pending': sum(1 for t in self.tasks.values() if t.status == TaskStatus.PENDING),
                'running': sum(1 for t in self.tasks.values() if t.status == TaskStatus.RUNNING),
                'overall_progress': self.current_job.total_progress,
                'estimated_remaining_time': self._estimate_remaining_time()
            }
            return stats
    
    def _estimate_remaining_time(self) -> float:
        """估算剩余时间"""
        completed_tasks = [t for t in self.tasks.values() 
                          if t.status == TaskStatus.COMPLETED and t.actual_duration > 0]
        
        if not completed_tasks:
            return 0.0
        
        avg_duration = sum(t.actual_duration for t in completed_tasks) / len(completed_tasks)
        remaining_tasks = sum(1 for t in self.tasks.values() 
                            if t.status in [TaskStatus.PENDING, TaskStatus.RUNNING])
        
        return avg_duration * remaining_tasks
    
    def cleanup_old_jobs(self, days: int = 7):
        """清理旧的任务文件"""
        cutoff_time = datetime.now() - timedelta(days=days)
        
        for filename in os.listdir(self.persistence_dir):
            if filename.endswith('.json'):
                file_path = os.path.join(self.persistence_dir, filename)
                try:
                    file_time = datetime.fromtimestamp(os.path.getmtime(file_path))
                    if file_time < cutoff_time:
                        os.unlink(file_path)
                except Exception:
                    pass  # 忽略清理错误


class RobustTaskExecutor:
    """强健的任务执行器 - 集成错误分类和智能重试"""
    
    def __init__(self, task_manager: TaskManager):
        self.task_manager = task_manager
        self.error_classifier = ErrorClassifier()
    
    def execute_task(self, task: TaskInfo, processor_func: Callable) -> bool:
        """执行单个任务，包含错误处理和重试逻辑"""
        task_id = task.task_id
        
        try:
            # 标记任务开始
            self.task_manager.mark_task_started(task_id)
            
            # 执行任务
            start_time = time.time()
            result = processor_func(task)
            duration = time.time() - start_time
            
            if result:
                # 任务成功
                self.task_manager.mark_task_completed(task_id, duration)
                return True
            else:
                # 任务失败但没有异常
                self.task_manager.mark_task_failed(
                    task_id, "任务执行失败", FailureReason.UNKNOWN
                )
                return False
                
        except Exception as e:
            # 分类错误并决定是否重试
            failure_reason = self.error_classifier.classify_error(e)
            should_retry = self.error_classifier.should_retry(failure_reason, task.retry_count)
            
            # 增加重试计数
            if task_id in self.task_manager.tasks:
                self.task_manager.tasks[task_id].retry_count += 1
            
            if not should_retry:
                # 不应该重试的错误，直接标记为最大重试次数
                if task_id in self.task_manager.tasks:
                    self.task_manager.tasks[task_id].retry_count = self.task_manager.tasks[task_id].max_retries
            
            self.task_manager.mark_task_failed(task_id, str(e), failure_reason)
            return False


class ErrorClassifier:
    """错误分类器 - 智能分析错误类型和重试策略"""
    
    def classify_error(self, error: Exception) -> FailureReason:
        """分类错误类型"""
        error_str = str(error).lower()
        
        if "no such file" in error_str or "file not found" in error_str:
            return FailureReason.FILE_NOT_FOUND
        elif "memory" in error_str or "out of memory" in error_str:
            return FailureReason.INSUFFICIENT_MEMORY
        elif "no space left" in error_str or "disk full" in error_str:
            return FailureReason.DISK_FULL
        elif "permission denied" in error_str or "access denied" in error_str:
            return FailureReason.PERMISSION_DENIED
        elif "ffmpeg" in error_str:
            return FailureReason.FFMPEG_ERROR
        elif "timeout" in error_str or "timed out" in error_str:
            return FailureReason.TIMEOUT
        elif "corrupt" in error_str or "invalid" in error_str:
            return FailureReason.CORRUPTION
        else:
            return FailureReason.UNKNOWN
    
    def should_retry(self, failure_reason: FailureReason, retry_count: int) -> bool:
        """判断是否应该重试"""
        # 不应该重试的错误类型
        no_retry_reasons = {
            FailureReason.FILE_NOT_FOUND,
            FailureReason.PERMISSION_DENIED,
            FailureReason.CORRUPTION
        }
        
        if failure_reason in no_retry_reasons:
            return False
        
        # 磁盘空间不足，重试次数限制为1次
        if failure_reason == FailureReason.DISK_FULL and retry_count >= 1:
            return False
        
        # 其他错误允许重试
        return retry_count < 3
