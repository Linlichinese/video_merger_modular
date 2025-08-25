"""
自动分割-合成流水线控制器

负责协调分割和合成任务的执行顺序，实现严格的两阶段处理流程
"""

import os
import logging
from typing import List, Dict, Optional, Callable
from datetime import datetime
from PyQt5.QtCore import QObject, pyqtSignal, QTimer

from .pipeline_states import (
    PipelineState, PipelineConfig, PipelineProgress, 
    PipelineStateManager, create_progress
)
from .batch_processor import BatchProcessor, BatchJobType
from .video_splitter import VideoSplitter


class PipelineController(QObject):
    """自动分割-合成流水线控制器"""
    
    # 信号定义
    state_changed = pyqtSignal(str)                    # 状态变更 (state_name)
    phase_progress = pyqtSignal(str, float)            # 阶段进度 (phase_name, progress)
    overall_progress = pyqtSignal(float)               # 整体进度 (progress)
    pipeline_completed = pyqtSignal(str)               # 流水线完成 (result_message)
    pipeline_failed = pyqtSignal(str, str)             # 流水线失败 (error_type, error_message)
    current_task_changed = pyqtSignal(str)             # 当前任务变更 (task_description)
    
    def __init__(self, batch_processor: BatchProcessor, parent=None):
        super().__init__(parent)
        
        # 核心组件
        self.batch_processor = batch_processor
        self.state_manager = PipelineStateManager()
        
        # 配置和状态
        self.config: Optional[PipelineConfig] = None
        self.progress = create_progress(PipelineState.IDLE)
        
        # 进度跟踪
        self.split_folder_progress: Dict[str, float] = {}
        self.merge_folder_progress: Dict[str, float] = {}
        self.split_output_folders: List[str] = []
        
        # 定时器用于进度更新
        self.progress_timer = QTimer()
        self.progress_timer.timeout.connect(self._update_progress)
        self.progress_timer.setInterval(500)  # 500ms更新一次
        
        # 连接批处理器信号
        self._connect_batch_processor_signals()
        
        # 日志
        self.logger = logging.getLogger(__name__)
    
    def _connect_batch_processor_signals(self):
        """连接批处理器的信号"""
        self.batch_processor.job_progress.connect(self._on_job_progress)
        self.batch_processor.job_completed.connect(self._on_job_completed)
        self.batch_processor.job_failed.connect(self._on_job_failed)
        self.batch_processor.batch_completed.connect(self._on_batch_completed)
        self.batch_processor.batch_failed.connect(self._on_batch_failed)
    
    def start_pipeline(self, config: PipelineConfig) -> bool:
        """启动流水线处理"""
        try:
            # 验证配置
            is_valid, error_msg = self._validate_config(config)
            if not is_valid:
                self.pipeline_failed.emit("配置错误", error_msg)
                return False
            
            # 保存配置
            self.config = config
            
            # 切换到分割状态
            if not self.state_manager.transition_to(PipelineState.SPLITTING):
                self.pipeline_failed.emit("状态错误", "无法启动分割流程")
                return False
            
            # 重置进度跟踪
            self._reset_progress_tracking()
            
            # 启动分割任务
            success = self._setup_split_jobs()
            if not success:
                self.state_manager.transition_to(PipelineState.FAILED)
                self.pipeline_failed.emit("启动错误", "无法创建分割任务")
                return False
            
            # 开始进度更新
            self.progress_timer.start()
            
            # 发出状态变更信号
            self.state_changed.emit(PipelineState.SPLITTING.value)
            self.current_task_changed.emit("正在分割视频文件...")
            
            self.logger.info(f"流水线启动成功，开始处理 {len(config.input_folders)} 个文件夹")
            return True
            
        except Exception as e:
            self.logger.error(f"启动流水线失败: {e}")
            self.pipeline_failed.emit("系统错误", str(e))
            return False
    
    def _validate_config(self, config: PipelineConfig) -> tuple[bool, str]:
        """验证流水线配置"""
        # 检查输入文件夹
        if not config.input_folders:
            return False, "未选择输入文件夹"
        
        for folder in config.input_folders:
            if not os.path.exists(folder):
                return False, f"输入文件夹不存在: {folder}"
            if not os.path.isdir(folder):
                return False, f"路径不是文件夹: {folder}"
        
        # 检查输出文件夹
        if not config.split_output_folder:
            return False, "未指定分割输出文件夹"
        
        if not config.merge_output_folder:
            return False, "未指定合成输出文件夹"
        
        # 检查分割参数
        if config.split_duration_range[0] >= config.split_duration_range[1]:
            return False, "分割时长范围设置错误"
        
        if config.split_duration_range[0] <= 0:
            return False, "分割时长不能小于等于0"
        
        # 检查合成参数
        if config.merge_clips_per_video <= 0:
            return False, "每视频片段数必须大于0"
        
        if config.merge_output_count <= 0:
            return False, "输出视频数量必须大于0"
        
        return True, ""
    
    def _reset_progress_tracking(self):
        """重置进度跟踪"""
        self.split_folder_progress.clear()
        self.merge_folder_progress.clear()
        self.split_output_folders.clear()
        
        # 初始化分割进度跟踪
        for folder in self.config.input_folders:
            self.split_folder_progress[folder] = 0.0
        
        # 重置进度对象
        self.progress = create_progress(PipelineState.SPLITTING)
        self.progress.split_total_folders = len(self.config.input_folders)
    
    def _setup_split_jobs(self) -> bool:
        """设置分割任务"""
        try:
            # 确保输出目录存在
            os.makedirs(self.config.split_output_folder, exist_ok=True)
            
            # 为每个输入文件夹创建分割任务
            for folder_path in self.config.input_folders:
                # 创建对应的输出子文件夹
                folder_name = os.path.basename(folder_path)
                output_subfolder = os.path.join(self.config.split_output_folder, folder_name)
                
                # 构建分割任务参数
                split_params = {
                    'input_folder': folder_path,
                    'output_folder': output_subfolder,
                    'duration_range': self.config.split_duration_range,
                    'resolution': self.config.split_resolution,
                    'bitrate': self.config.split_bitrate,
                    'quality': self.config.split_quality,
                    'delete_original': self.config.delete_original_after_split,
                    'use_gpu': self.config.use_gpu
                }
                
                # 添加到批处理器
                job_id = self.batch_processor.add_split_job(
                    folder_path=folder_path,
                    output_folder=output_subfolder,
                    **split_params
                )
                
                if job_id:
                    self.logger.info(f"添加分割任务: {folder_path} -> {output_subfolder}")
                else:
                    self.logger.error(f"添加分割任务失败: {folder_path}")
                    return False
            
            return True
            
        except Exception as e:
            self.logger.error(f"设置分割任务失败: {e}")
            return False
    
    def _on_job_progress(self, job_id: str, progress: float):
        """处理单个任务进度更新"""
        # 根据任务类型更新对应的进度
        job_info = self.batch_processor.get_job_info(job_id)
        if not job_info:
            return
        
        if job_info.get('type') == BatchJobType.SPLIT:
            folder_path = job_info.get('folder_path')
            if folder_path in self.split_folder_progress:
                self.split_folder_progress[folder_path] = progress
        
        elif job_info.get('type') == BatchJobType.MERGE:
            folder_path = job_info.get('folder_path')
            if folder_path in self.merge_folder_progress:
                self.merge_folder_progress[folder_path] = progress
    
    def _on_job_completed(self, job_id: str, result: dict):
        """处理单个任务完成"""
        job_info = self.batch_processor.get_job_info(job_id)
        if not job_info:
            return
        
        if job_info.get('type') == BatchJobType.SPLIT:
            folder_path = job_info.get('folder_path')
            if folder_path in self.split_folder_progress:
                self.split_folder_progress[folder_path] = 1.0
                self.progress.split_completed_folders += 1
                
                # 记录分割输出文件夹
                output_folder = job_info.get('output_folder')
                if output_folder and os.path.exists(output_folder):
                    self.split_output_folders.append(output_folder)
                
                self.logger.info(f"分割任务完成: {folder_path}")
        
        elif job_info.get('type') == BatchJobType.MERGE:
            folder_path = job_info.get('folder_path')
            if folder_path in self.merge_folder_progress:
                self.merge_folder_progress[folder_path] = 1.0
                self.progress.merge_completed_folders += 1
                self.logger.info(f"合成任务完成: {folder_path}")
    
    def _on_job_failed(self, job_id: str, error: str):
        """处理单个任务失败"""
        self.logger.error(f"任务失败 {job_id}: {error}")
        
        # 如果是分割阶段的任务失败，整个流水线失败
        if self.state_manager.get_state() == PipelineState.SPLITTING:
            self.state_manager.transition_to(PipelineState.FAILED)
            self.pipeline_failed.emit("分割任务失败", f"任务 {job_id} 失败: {error}")
            self.progress_timer.stop()
        
        # 如果是合成阶段的任务失败，整个流水线失败
        elif self.state_manager.get_state() == PipelineState.MERGING:
            self.state_manager.transition_to(PipelineState.FAILED)
            self.pipeline_failed.emit("合成任务失败", f"任务 {job_id} 失败: {error}")
            self.progress_timer.stop()
    
    def _on_batch_completed(self, batch_type: str):
        """处理批次完成"""
        if batch_type == BatchJobType.SPLIT.value:
            self._on_split_batch_completed()
        elif batch_type == BatchJobType.MERGE.value:
            self._on_merge_batch_completed()
    
    def _on_batch_failed(self, batch_type: str, error: str):
        """处理批次失败"""
        self.logger.error(f"批次失败 {batch_type}: {error}")
        self.state_manager.transition_to(PipelineState.FAILED)
        self.pipeline_failed.emit(f"{batch_type}批次失败", error)
        self.progress_timer.stop()
    
    def _on_split_batch_completed(self):
        """分割批次完成处理"""
        self.logger.info("所有分割任务完成")
        
        # 验证分割结果
        if not self._validate_split_results():
            self.state_manager.transition_to(PipelineState.FAILED)
            self.pipeline_failed.emit("分割验证失败", "分割输出文件验证失败")
            self.progress_timer.stop()
            return
        
        # 切换到分割完成状态
        self.state_manager.transition_to(PipelineState.SPLIT_COMPLETED)
        self.state_changed.emit(PipelineState.SPLIT_COMPLETED.value)
        self.current_task_changed.emit("分割完成，准备开始合成...")
        
        # 自动启动合成阶段
        self._start_merge_phase()
    
    def _validate_split_results(self) -> bool:
        """验证分割结果"""
        try:
            for output_folder in self.split_output_folders:
                if not os.path.exists(output_folder):
                    self.logger.error(f"分割输出文件夹不存在: {output_folder}")
                    return False
                
                # 检查是否有视频文件
                video_files = []
                for file in os.listdir(output_folder):
                    if file.lower().endswith(('.mp4', '.avi', '.mov', '.mkv')):
                        video_files.append(file)
                
                if not video_files:
                    self.logger.error(f"分割输出文件夹无视频文件: {output_folder}")
                    return False
                
                self.logger.info(f"分割输出验证通过: {output_folder} ({len(video_files)} 个文件)")
            
            return True
            
        except Exception as e:
            self.logger.error(f"验证分割结果失败: {e}")
            return False
    
    def _start_merge_phase(self):
        """启动合成阶段"""
        try:
            # 切换到合成状态
            if not self.state_manager.transition_to(PipelineState.MERGING):
                self.pipeline_failed.emit("状态错误", "无法启动合成流程")
                return
            
            # 设置合成任务
            success = self._setup_merge_jobs()
            if not success:
                self.state_manager.transition_to(PipelineState.FAILED)
                self.pipeline_failed.emit("合成启动失败", "无法创建合成任务")
                return
            
            # 更新进度跟踪
            self.progress.merge_total_folders = len(self.split_output_folders)
            
            # 发出状态变更信号
            self.state_changed.emit(PipelineState.MERGING.value)
            self.current_task_changed.emit("正在合成视频文件...")
            
            self.logger.info(f"合成阶段启动成功，处理 {len(self.split_output_folders)} 个文件夹")
            
        except Exception as e:
            self.logger.error(f"启动合成阶段失败: {e}")
            self.state_manager.transition_to(PipelineState.FAILED)
            self.pipeline_failed.emit("合成启动错误", str(e))
    
    def _setup_merge_jobs(self) -> bool:
        """设置合成任务"""
        try:
            # 确保合成输出目录存在
            os.makedirs(self.config.merge_output_folder, exist_ok=True)
            
            # 初始化合成进度跟踪
            for folder_path in self.split_output_folders:
                self.merge_folder_progress[folder_path] = 0.0
            
            # 为每个分割输出文件夹创建合成任务
            for folder_path in self.split_output_folders:
                # 构建合成任务参数
                merge_params = {
                    'input_folder': folder_path,
                    'output_folder': self.config.merge_output_folder,
                    'clips_per_video': self.config.merge_clips_per_video,
                    'output_count': self.config.merge_output_count,
                    'allow_reuse': self.config.merge_allow_reuse,
                    'audio_enabled': self.config.merge_audio_enabled,
                    'resolution': self.config.merge_resolution,
                    'bitrate': self.config.merge_bitrate,
                    'use_gpu': self.config.use_gpu
                }
                
                # 添加到批处理器
                job_id = self.batch_processor.add_merge_job(
                    folder_path=folder_path,
                    output_folder=self.config.merge_output_folder,
                    **merge_params
                )
                
                if job_id:
                    self.logger.info(f"添加合成任务: {folder_path}")
                else:
                    self.logger.error(f"添加合成任务失败: {folder_path}")
                    return False
            
            return True
            
        except Exception as e:
            self.logger.error(f"设置合成任务失败: {e}")
            return False
    
    def _on_merge_batch_completed(self):
        """合成批次完成处理"""
        self.logger.info("所有合成任务完成")
        
        # 切换到完成状态
        self.state_manager.transition_to(PipelineState.COMPLETED)
        self.progress_timer.stop()
        
        # 发出完成信号
        self.state_changed.emit(PipelineState.COMPLETED.value)
        self.current_task_changed.emit("流水线处理完成")
        
        result_msg = f"流水线处理成功完成！\n" \
                    f"处理了 {len(self.config.input_folders)} 个输入文件夹\n" \
                    f"生成了 {len(self.split_output_folders)} 个分割文件夹\n" \
                    f"输出路径: {self.config.merge_output_folder}"
        
        self.pipeline_completed.emit(result_msg)
    
    def _update_progress(self):
        """更新整体进度"""
        if not self.config:
            return
        
        current_state = self.state_manager.get_state()
        
        # 计算分割进度
        if self.split_folder_progress:
            split_progress = sum(self.split_folder_progress.values()) / len(self.split_folder_progress)
        else:
            split_progress = 0.0
        
        # 计算合成进度
        if self.merge_folder_progress:
            merge_progress = sum(self.merge_folder_progress.values()) / len(self.merge_folder_progress)
        else:
            merge_progress = 0.0
        
        # 更新进度对象
        self.progress.split_progress = split_progress
        self.progress.merge_progress = merge_progress
        
        # 计算整体进度 (分割占50%，合成占50%)
        if current_state in [PipelineState.SPLITTING, PipelineState.SPLIT_COMPLETED]:
            overall_progress = split_progress * 0.5
        elif current_state == PipelineState.MERGING:
            overall_progress = 0.5 + (merge_progress * 0.5)
        elif current_state == PipelineState.COMPLETED:
            overall_progress = 1.0
        else:
            overall_progress = 0.0
        
        self.progress.overall_progress = overall_progress
        
        # 发出进度信号
        self.overall_progress.emit(overall_progress)
        
        if current_state == PipelineState.SPLITTING:
            self.phase_progress.emit("分割阶段", split_progress)
        elif current_state == PipelineState.MERGING:
            self.phase_progress.emit("合成阶段", merge_progress)
    
    def cancel_pipeline(self):
        """取消流水线处理"""
        if self.state_manager.get_state() in [PipelineState.SPLITTING, PipelineState.MERGING]:
            # 停止批处理器
            self.batch_processor.stop_all_jobs()
            
            # 切换状态
            self.state_manager.transition_to(PipelineState.CANCELLED)
            self.progress_timer.stop()
            
            # 发出信号
            self.state_changed.emit(PipelineState.CANCELLED.value)
            self.current_task_changed.emit("已取消")
            
            self.logger.info("用户取消了流水线处理")
    
    def pause_pipeline(self):
        """暂停流水线处理"""
        if self.state_manager.get_state() in [PipelineState.SPLITTING, PipelineState.MERGING]:
            # 暂停批处理器
            self.batch_processor.pause_all_jobs()
            
            # 切换状态
            self.state_manager.transition_to(PipelineState.PAUSED)
            
            # 发出信号
            self.state_changed.emit(PipelineState.PAUSED.value)
            self.current_task_changed.emit("已暂停")
    
    def resume_pipeline(self):
        """恢复流水线处理"""
        if self.state_manager.get_state() == PipelineState.PAUSED:
            # 恢复批处理器
            self.batch_processor.resume_all_jobs()
            
            # 切换回原状态 (这里简化处理，实际需要记录暂停前的状态)
            if self.progress.split_progress < 1.0:
                self.state_manager.transition_to(PipelineState.SPLITTING)
                self.current_task_changed.emit("正在分割视频文件...")
            else:
                self.state_manager.transition_to(PipelineState.MERGING)
                self.current_task_changed.emit("正在合成视频文件...")
            
            # 发出信号
            self.state_changed.emit(self.state_manager.get_state().value)
    
    def get_current_state(self) -> PipelineState:
        """获取当前状态"""
        return self.state_manager.get_state()
    
    def get_progress(self) -> PipelineProgress:
        """获取当前进度"""
        return self.progress
    
    def reset(self):
        """重置控制器"""
        # 停止所有任务
        if self.state_manager.get_state() not in [PipelineState.IDLE, PipelineState.COMPLETED, PipelineState.FAILED]:
            self.cancel_pipeline()
        
        # 重置状态
        self.state_manager.reset()
        self.config = None
        self.progress = create_progress(PipelineState.IDLE)
        
        # 清理进度跟踪
        self.split_folder_progress.clear()
        self.merge_folder_progress.clear()
        self.split_output_folders.clear()
        
        # 停止进度更新
        self.progress_timer.stop()
        
        # 发出信号
        self.state_changed.emit(PipelineState.IDLE.value)
        self.current_task_changed.emit("就绪")
        self.overall_progress.emit(0.0)
