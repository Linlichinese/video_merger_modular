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
    split_bitrate: str                     # "4000k"
    split_quality: str                     # "high"/"medium"/"low"
    split_delete_original: bool            # 是否删除原文件
    
    # 合成配置
    merge_videos_per_output: int           # 每个输出视频包含的片段数
    merge_total_outputs: int               # 总输出视频数
    merge_resolution: str                  # "1920x1080"
    merge_bitrate: str                     # "5000k"
    merge_audio_settings: dict             # 音频设置
    merge_reuse_material: bool             # 是否重复使用素材
    
    # 全局配置
    input_folders: list                    # 输入文件夹列表
    output_folder: str                     # 输出文件夹路径
    use_gpu: bool                         # 是否使用GPU加速


class StateTransitionManager:
    """状态转换管理器"""
    
    # 定义合法的状态转换
    VALID_TRANSITIONS: Dict[PipelineState, Set[PipelineState]] = {
        PipelineState.IDLE: {
            PipelineState.CONFIGURING,
            PipelineState.SPLITTING
        },
        PipelineState.CONFIGURING: {
            PipelineState.SPLITTING,
            PipelineState.CANCELLED,
            PipelineState.IDLE
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
            PipelineState.IDLE
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
            PipelineState.CANCELLED,
            PipelineState.IDLE
        },
        PipelineState.COMPLETED: {
            PipelineState.IDLE
        },
        PipelineState.FAILED: {
            PipelineState.IDLE,
            PipelineState.SPLITTING,  # 允许重试
            PipelineState.MERGING     # 允许重试
        },
        PipelineState.CANCELLED: {
            PipelineState.IDLE
        }
    }
    
    def __init__(self):
        self.current_state = PipelineState.IDLE
        self.state_history = [PipelineState.IDLE]
        self.transition_timestamps = {PipelineState.IDLE: datetime.now()}
    
    def can_transition_to(self, target_state: PipelineState) -> bool:
        """检查是否可以转换到目标状态"""
        return target_state in self.VALID_TRANSITIONS.get(self.current_state, set())
    
    def transition_to(self, target_state: PipelineState) -> bool:
        """执行状态转换"""
        if not self.can_transition_to(target_state):
            return False
        
        # 记录状态转换
        self.current_state = target_state
        self.state_history.append(target_state)
        self.transition_timestamps[target_state] = datetime.now()
        
        return True
    
    def get_current_state(self) -> PipelineState:
        """获取当前状态"""
        return self.current_state
    
    def get_state_duration(self, state: PipelineState) -> Optional[float]:
        """获取指定状态的持续时间（秒）"""
        if state not in self.transition_timestamps:
            return None
        
        start_time = self.transition_timestamps[state]
        
        # 如果是当前状态，计算到现在的时间
        if state == self.current_state:
            return (datetime.now() - start_time).total_seconds()
        
        # 如果不是当前状态，找到下一个状态的时间
        state_index = None
        for i, hist_state in enumerate(self.state_history):
            if hist_state == state:
                state_index = i
                break
        
        if state_index is None or state_index >= len(self.state_history) - 1:
            return None
        
        next_state = self.state_history[state_index + 1]
        end_time = self.transition_timestamps[next_state]
        
        return (end_time - start_time).total_seconds()
    
    def reset(self):
        """重置状态管理器"""
        self.current_state = PipelineState.IDLE
        self.state_history = [PipelineState.IDLE]
        self.transition_timestamps = {PipelineState.IDLE: datetime.now()}
    
    def get_state_summary(self) -> dict:
        """获取状态摘要信息"""
        return {
            'current_state': self.current_state.value,
            'total_states': len(self.state_history),
            'current_duration': self.get_state_duration(self.current_state),
            'state_history': [state.value for state in self.state_history]
        }
