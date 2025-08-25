"""
视频合成核心模块

该模块包含视频处理的核心功能，包括视频选择、处理和合成逻辑。
"""

from .video_processor import VideoProcessor
from .audio_processor import AudioProcessor
from .sequence_selector import SequenceDiversitySelector
from .ffmpeg_processor import FFmpegGPUProcessor
from .gpu_config import GPUConfigManager

__all__ = ['VideoProcessor', 'AudioProcessor', 'SequenceDiversitySelector', 
           'FFmpegGPUProcessor', 'GPUConfigManager']
