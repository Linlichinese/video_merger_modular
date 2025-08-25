"""
音频处理器模块 - 纯FFmpeg版本

负责构建FFmpeg音频滤镜链，避免MoviePy造成的文件占用问题
"""

import os
import random
from typing import List, Tuple, Dict


class AudioProcessor:
    """音频处理器，使用纯FFmpeg进行音频处理"""
    
    def __init__(self, audio_settings):
        """
        初始化音频处理器
        
        Args:
            audio_settings (dict): 音频设置字典
        """
        self.audio_settings = audio_settings
    
    def build_audio_filter_chain(self, total_duration: float) -> Tuple[List[str], str]:
        """
        构建FFmpeg音频滤镜链
        
        Args:
            total_duration (float): 视频总时长（秒）
            
        Returns:
            Tuple[List[str], str]: (额外音频输入文件列表, 音频滤镜字符串)
        """
        # 校验时长参数
        if total_duration <= 0:
            raise ValueError(f"Invalid total_duration: {total_duration}. Must be positive.")
        
        audio_inputs = []
        filters = []
        
        # 调试输出：显示音频设置
        print(f"[AudioProcessor] 音频设置: {self.audio_settings}")
        print(f"[AudioProcessor] 目标时长: {total_duration} 秒")
        
        # 检查是否需要音频处理
        has_replace_audio = (self.audio_settings['replace_audio'] and 
                           self.audio_settings['replace_audio_path'])
        has_background_audio = (self.audio_settings['background_audio'] and 
                              self.audio_settings['background_audio_path'])
        
        print(f"[AudioProcessor] 替换音频: {has_replace_audio}, 背景音频: {has_background_audio}")
        
        if not has_replace_audio and not has_background_audio:
            # 没有音频处理需求，返回空
            print(f"[AudioProcessor] 没有额外音频处理需求，返回空滤镜")
            return [], ""
        
        audio_labels = []
        
        # 处理替换音频
        if has_replace_audio:
            replace_audio_path = self._get_audio_path(
                self.audio_settings['replace_audio_path'],
                self.audio_settings.get('replace_audio_is_folder', False)
            )
            audio_inputs.append(replace_audio_path)
            
            # 音频输入索引需要考虑前面的视频输入数量
            # 这里先用占位符，后面会在video_processor中调整
            input_index = f"AUDIO_INPUT_{len(audio_inputs)}"
            replace_filter, replace_label = self._build_replace_audio_filter(
                input_index, total_duration, 
                self.audio_settings['replace_volume'] / 100
            )
            filters.append(replace_filter)
            audio_labels.append(replace_label)
        
        # 处理背景音频
        if has_background_audio:
            bg_audio_path = self._get_audio_path(
                self.audio_settings['background_audio_path'],
                self.audio_settings.get('background_audio_is_folder', False)
            )
            audio_inputs.append(bg_audio_path)
            
            input_index = f"AUDIO_INPUT_{len(audio_inputs)}"
            bg_filter, bg_label = self._build_background_audio_filter(
                input_index, total_duration,
                self.audio_settings['background_volume'] / 100
            )
            filters.append(bg_filter)
            audio_labels.append(bg_label)
        
        # 合并音频滤镜
        if len(filters) == 1:
            # 只有一个音频源
            final_filter = filters[0]
        else:
            # 多个音频源需要混合
            mix_filter = self._build_mix_filter(audio_labels)
            final_filter = f"{';'.join(filters)};{mix_filter}"
        
        print(f"[AudioProcessor] 生成的音频滤镜: {final_filter}")
        print(f"[AudioProcessor] 音频输入文件: {audio_inputs}")
        
        return audio_inputs, final_filter
    
    def _build_replace_audio_filter(self, input_index, duration: float, volume: float) -> Tuple[str, str]:
        """
        构建替换音频的滤镜
        
        Args:
            input_index: 音频输入的索引
            duration: 目标时长（秒）
            volume: 音量（0.0-1.0）
            
        Returns:
            Tuple[str, str]: (滤镜字符串, 输出标签)
        """
        label = f"replace_audio"
        
        # 构建滤镜：限制时长 + 音量调节（不使用aloop避免音频质量问题）
        filter_str = f"[{input_index}:a]atrim=end={duration},volume={volume}[{label}]"
        
        return filter_str, label
    
    def _build_background_audio_filter(self, input_index, duration: float, volume: float) -> Tuple[str, str]:
        """
        构建背景音频的滤镜
        
        Args:
            input_index: 音频输入的索引
            duration: 目标时长（秒）
            volume: 音量（0.0-1.0）
            
        Returns:
            Tuple[str, str]: (滤镜字符串, 输出标签)
        """
        label = f"bg_audio"
        
        # 构建滤镜：限制时长 + 音量调节（不使用aloop避免音频质量问题）
        filter_str = f"[{input_index}:a]atrim=end={duration},volume={volume}[{label}]"
        
        return filter_str, label
    
    def _build_mix_filter(self, audio_labels: List[str]) -> str:
        """
        构建音频混合滤镜
        
        Args:
            audio_labels: 音频标签列表
            
        Returns:
            str: 混合滤镜字符串
        """
        inputs = "".join(f"[{label}]" for label in audio_labels)
        return f"{inputs}amix=inputs={len(audio_labels)}:duration=longest:dropout_transition=2[aout]"
    
    def has_audio_processing(self) -> bool:
        """
        检查是否需要音频处理
        
        Returns:
            bool: 是否需要音频处理
        """
        has_replace = (self.audio_settings['replace_audio'] and 
                      self.audio_settings['replace_audio_path'])
        has_background = (self.audio_settings['background_audio'] and 
                         self.audio_settings['background_audio_path'])
        
        return has_replace or has_background
    
    def build_audio_filter_with_original(self, total_duration: float, has_original_audio: bool) -> Tuple[List[str], str]:
        """
        构建包含原音频处理的FFmpeg音频滤镜链
        
        Args:
            total_duration (float): 视频总时长（秒）
            has_original_audio (bool): 是否有原音频流可用
            
        Returns:
            Tuple[List[str], str]: (额外音频输入文件列表, 音频滤镜字符串)
        """
        # 校验时长参数
        if total_duration <= 0:
            raise ValueError(f"Invalid total_duration: {total_duration}. Must be positive.")
        
        audio_inputs = []
        filters = []
        audio_labels = []
        
        # 调试输出
        print(f"[AudioProcessor] 构建包含原音频的滤镜链")
        print(f"[AudioProcessor] 音频设置: {self.audio_settings}")
        print(f"[AudioProcessor] 有原音频: {has_original_audio}")
        
        # 处理原音频
        if self.audio_settings['keep_original'] and has_original_audio:
            if self.audio_settings['original_volume'] != 100:
                # 需要调整原音频音量
                orig_volume = self.audio_settings['original_volume'] / 100.0
                orig_filter = f"[orig_audio]volume={orig_volume}[orig_audio_vol]"
                filters.append(orig_filter)
                audio_labels.append("orig_audio_vol")
            else:
                # 直接使用原音频
                audio_labels.append("orig_audio")
        
        # 检查额外音频源
        has_replace_audio = (self.audio_settings['replace_audio'] and 
                           self.audio_settings['replace_audio_path'])
        has_background_audio = (self.audio_settings['background_audio'] and 
                              self.audio_settings['background_audio_path'])
        
        # 处理替换音频
        if has_replace_audio:
            replace_audio_path = self._get_audio_path(
                self.audio_settings['replace_audio_path'],
                self.audio_settings.get('replace_audio_is_folder', False)
            )
            audio_inputs.append(replace_audio_path)
            
            input_index = f"AUDIO_INPUT_{len(audio_inputs)}"
            replace_filter, replace_label = self._build_replace_audio_filter(
                input_index, total_duration, 
                self.audio_settings['replace_volume'] / 100
            )
            filters.append(replace_filter)
            audio_labels.append(replace_label)
        
        # 处理背景音频
        if has_background_audio:
            bg_audio_path = self._get_audio_path(
                self.audio_settings['background_audio_path'],
                self.audio_settings.get('background_audio_is_folder', False)
            )
            audio_inputs.append(bg_audio_path)
            
            input_index = f"AUDIO_INPUT_{len(audio_inputs)}"
            bg_filter, bg_label = self._build_background_audio_filter(
                input_index, total_duration,
                self.audio_settings['background_volume'] / 100
            )
            filters.append(bg_filter)
            audio_labels.append(bg_label)
        
        # 构建最终混合滤镜
        if len(audio_labels) == 0:
            return [], ""
        elif len(audio_labels) == 1:
            # 只有一个音频源，直接输出
            if filters:
                final_filter = f"{';'.join(filters)};[{audio_labels[0]}]copy[aout]"
            else:
                final_filter = f"[{audio_labels[0]}]copy[aout]"
        else:
            # 多个音频源需要混合
            mix_filter = self._build_mix_filter(audio_labels)
            if filters:
                final_filter = f"{';'.join(filters)};{mix_filter}"
            else:
                final_filter = mix_filter
        
        print(f"[AudioProcessor] 最终音频滤镜: {final_filter}")
        print(f"[AudioProcessor] 音频输入文件: {audio_inputs}")
        
        return audio_inputs, final_filter
    
    def _get_audio_path(self, path: str, is_folder: bool) -> str:
        """
        获取音频文件路径，如果是文件夹则随机选择其中的音频文件
        
        Args:
            path: 文件或文件夹路径
            is_folder: 是否为文件夹
            
        Returns:
            str: 音频文件路径
        """
        if not is_folder:
            return path
        
        # 从文件夹中获取音频文件列表
        audio_files = self._get_audio_files_from_folder(path)
        if not audio_files:
            supported_formats = ', '.join(self._get_supported_audio_extensions())
            raise Exception(f"文件夹 {path} 中没有找到音频文件。支持的格式: {supported_formats}")
        
        # 随机选择一个音频文件
        selected_audio = random.choice(audio_files)
        print(f"[AudioProcessor] 选择的音频文件: {selected_audio}")
        
        # 验证选择的文件是否存在且可读
        if not os.path.exists(selected_audio):
            raise Exception(f"选择的音频文件不存在: {selected_audio}")
        if not os.access(selected_audio, os.R_OK):
            raise Exception(f"选择的音频文件不可读: {selected_audio}")
        
        return selected_audio
    
    def _get_supported_audio_extensions(self) -> List[str]:
        """获取支持的音频文件扩展名列表"""
        return ['.mp3', '.wav', '.ogg', '.flac', '.m4a', '.aac', '.wma']
    
    def _get_audio_files_from_folder(self, folder_path: str) -> List[str]:
        """
        从文件夹中获取音频文件列表
        
        Args:
            folder_path: 文件夹路径
            
        Returns:
            List[str]: 音频文件路径列表
        """
        audio_extensions = tuple(self._get_supported_audio_extensions())
        try:
            audio_files = []
            for file_name in os.listdir(folder_path):
                if file_name.lower().endswith(audio_extensions):
                    file_path = os.path.join(folder_path, file_name)
                    # 检查文件是否可读
                    if os.access(file_path, os.R_OK):
                        audio_files.append(file_path)
                    else:
                        print(f"[AudioProcessor] 警告: 音频文件不可读，跳过: {file_path}")
            return audio_files
        except Exception as e:
            print(f"[AudioProcessor] 读取文件夹 {folder_path} 时出错: {e}")
            return []

    # 兼容性方法 - 为了不破坏现有代码
    def process_final_audio(self, total_duration):
        """
        兼容性方法：返回None表示使用FFmpeg处理音频
        
        Args:
            total_duration (float): 视频总时长
            
        Returns:
            None: 表示使用FFmpeg滤镜链处理音频
        """
        # 这个方法保留是为了兼容现有的video_processor代码
        # 实际的音频处理会通过build_audio_filter_chain完成
        return None