"""
流水线状态管理模块

定义自动分割-合成流水线的状态枚举和转换逻辑
"""

from enum import Enum
from typing import Dict, Set, Optional
from dataclasses import dataclass
from datetime import datetime


class PipelineState(Enum):
    """流水线状态枚举"""
    IDLE = "idle"                           # 空闲状态
    CONFIGURING = "configuring"             # 配置阶段
    SPLITTING = "splitting"                  # 分割执行中
    SPLIT_COMPLETED = "split_completed"     # 分割完成，等待确认
    MERGING = "merging"                     # 合成执行中
    COMPLETED = "completed"                 # 流水线完成
    FAILED = "failed"                       # 执行失败
    CANCELLED = "cancelled"                 # 用户取消
    PAUSED = "paused"                       # 暂停状态


@dataclass
class PipelineConfig:
    """流水线配置数据结构"""
    # 分割配置
    split_duration_range: tuple            # (min_seconds, max_seconds)
    split_resolution: Optional[str]        # "1920x1080" or None for original
    split_bitrate: Optional[str]           # "5000k" or None for original
    split_quality: str                     # "高质量", "中等质量", "快速"
    delete_original_after_split: bool      # 分割后删除原文件
    
    # 合成配置
    merge_clips_per_video: int             # 每个合成视频的片段数
    merge_output_count: int                # 输出视频数量
    merge_allow_reuse: bool                # 允许素材重复使用
    merge_audio_enabled: bool              # 启用音频
    merge_resolution: Optional[str]        # 合成输出分辨率
    merge_bitrate: Optional[str]           # 合成输出码率
    
    # 全局配置
    input_folders: list                    # 输入文件夹列表
    split_output_folder: str               # 分割输出文件夹
    merge_output_folder: str               # 合成输出文件夹
    use_gpu: bool                          # 是否使用GPU加速


@dataclass
class PipelineProgress:
    """流水线进度数据结构"""
    current_state: PipelineState
    split_progress: float                  # 分割阶段进度 0.0-1.0
    merge_progress: float                  # 合成阶段进度 0.0-1.0
    overall_progress: float               # 整体进度 0.0-1.0
    current_task: str                     # 当前任务描述
    estimated_time_remaining: Optional[int]  # 预估剩余时间(秒)
    
    # 详细进度信息
    split_completed_folders: int          # 已完成分割的文件夹数
    split_total_folders: int              # 总文件夹数
    merge_completed_folders: int          # 已完成合成的文件夹数
    merge_total_folders: int              # 需要合成的文件夹数


class PipelineStateManager:
    """流水线状态管理器"""
    
    # 定义合法的状态转换
    VALID_TRANSITIONS: Dict[PipelineState, Set[PipelineState]] = {
        PipelineState.IDLE: {
            PipelineState.CONFIGURING,
            PipelineState.SPLITTING
        },
        PipelineState.CONFIGURING: {
            PipelineState.IDLE,
            PipelineState.SPLITTING,
            PipelineState.CANCELLED
        },
        PipelineState.SPLITTING: {
            PipelineState.SPLIT_COMPLETED,
            PipelineState.FAILED,
            PipelineState.CANCELLED,
            PipelineState.PAUSED
        },
        PipelineState.SPLIT_COMPLETED: {
            PipelineState.MERGING,
            PipelineState.CANCELLED,
            PipelineState.FAILED
        },
        PipelineState.MERGING: {
            PipelineState.COMPLETED,
            PipelineState.FAILED,
            PipelineState.CANCELLED,
            PipelineState.PAUSED
        },
        PipelineState.PAUSED: {
            PipelineState.SPLITTING,
            PipelineState.MERGING,
            PipelineState.CANCELLED
        },
        PipelineState.COMPLETED: {
            PipelineState.IDLE
        },
        PipelineState.FAILED: {
            PipelineState.IDLE,
            PipelineState.CONFIGURING
        },
        PipelineState.CANCELLED: {
            PipelineState.IDLE,
            PipelineState.CONFIGURING
        }
    }
    
    def __init__(self):
        self.current_state = PipelineState.IDLE
        self.state_history = [(datetime.now(), PipelineState.IDLE)]
    
    def can_transition_to(self, new_state: PipelineState) -> bool:
        """检查是否可以转换到新状态"""
        return new_state in self.VALID_TRANSITIONS.get(self.current_state, set())
    
    def transition_to(self, new_state: PipelineState) -> bool:
        """转换到新状态"""
        if not self.can_transition_to(new_state):
            return False
        
        self.current_state = new_state
        self.state_history.append((datetime.now(), new_state))
        return True
    
    def get_state(self) -> PipelineState:
        """获取当前状态"""
        return self.current_state
    
    def get_state_history(self) -> list:
        """获取状态历史"""
        return self.state_history.copy()
    
    def reset(self):
        """重置到空闲状态"""
        self.current_state = PipelineState.IDLE
        self.state_history = [(datetime.now(), PipelineState.IDLE)]


def create_default_config() -> PipelineConfig:
    """创建默认的流水线配置"""
    return PipelineConfig(
        # 分割配置
        split_duration_range=(2, 4),
        split_resolution=None,  # 保持原分辨率
        split_bitrate=None,     # 保持原码率
        split_quality="中等质量",
        delete_original_after_split=False,
        
        # 合成配置
        merge_clips_per_video=3,
        merge_output_count=5,
        merge_allow_reuse=True,
        merge_audio_enabled=True,
        merge_resolution=None,  # 保持原分辨率
        merge_bitrate=None,     # 保持原码率
        
        # 全局配置
        input_folders=[],
        split_output_folder="",
        merge_output_folder="",
        use_gpu=True
    )


def create_progress(state: PipelineState) -> PipelineProgress:
    """创建默认的进度对象"""
    return PipelineProgress(
        current_state=state,
        split_progress=0.0,
        merge_progress=0.0,
        overall_progress=0.0,
        current_task="准备中...",
        estimated_time_remaining=None,
        split_completed_folders=0,
        split_total_folders=0,
        merge_completed_folders=0,
        merge_total_folders=0
    )