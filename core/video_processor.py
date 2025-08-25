"""
视频处理器模块

负责视频文件的选择、处理和合成逻辑，集成了 SequenceDiversitySelector 
以确保生成的素材组合顺序完全不重复，且连续2个元素的顺序也不重复。
"""

import os
import random
import time
import subprocess
from datetime import datetime
from PyQt5.QtCore import QThread, pyqtSignal
from moviepy.editor import VideoFileClip, concatenate_videoclips
from .audio_processor import AudioProcessor
from .sequence_selector import SequenceDiversitySelector
from .video_splitter import SegmentDeduplicator, get_split_segments_from_folder



def generate_unique_filename(output_folder: str, base_name: str, extension: str = "mp4") -> str:
    """
    生成唯一的文件名，避免覆盖现有文件
    
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


class VideoProcessor(QThread):
    """视频处理线程，负责后台处理视频合成，避免UI卡顿"""
    progress_updated = pyqtSignal(int)
    process_finished = pyqtSignal(str)
    detailed_progress_updated = pyqtSignal(float)  # 详细进度信号 (0.0-1.0)
    
    def __init__(self, input_folder, output_folder, videos_per_output, total_outputs, 
                 resolution, bitrate, reuse_material, audio_settings):
        super().__init__()
        self.input_folder = input_folder
        self.output_folder = output_folder
        self.videos_per_output = videos_per_output
        self.total_outputs = total_outputs
        self.resolution = resolution
        self.bitrate = bitrate
        self.reuse_material = reuse_material
        self.audio_settings = audio_settings
        self.running = True
        self._cancel_requested = False
        
        # 简化资源管理 - 参考副本版本策略
        
        # 获取所有视频文件
        self.video_extensions = ('.mp4', '.avi', '.mov', '.mkv', '.flv', '.wmv', '.mpeg', '.mpg')
        all_video_files = [f for f in os.listdir(input_folder) 
                          if f.lower().endswith(self.video_extensions)]
        if not all_video_files:
            raise ValueError("输入文件夹中没有找到视频文件")
        
        # 检测是否有分割片段，如果有则使用分割片段去重逻辑
        split_segments = get_split_segments_from_folder(input_folder)
        self.has_split_segments = len(split_segments) > 0
        
        if self.has_split_segments:
            # 如果检测到分割片段，使用分割片段列表
            self.video_files = [os.path.basename(seg) for seg in split_segments]
            print(f"检测到 {len(self.video_files)} 个分割片段，将使用去重逻辑")
        else:
            # 否则使用所有视频文件
            self.video_files = all_video_files
        
        # 使用 SequenceDiversitySelector 进行智能素材选择（启用持久化）
        # 使用标准的持久化文件路径生成逻辑
        dummy_selector = SequenceDiversitySelector(["dummy"], 1)
        persistence_file = dummy_selector.get_persistence_file_path(input_folder)
        
        self.sequence_selector = SequenceDiversitySelector(self.video_files, videos_per_output, persistence_file)
        
        # 音频处理器
        self.audio_processor = AudioProcessor(audio_settings)
        
        # 传统的素材使用记录（兼容模式，当不重用素材时使用）
        self.used_files = set()
    
    def run(self):
        """线程运行函数，处理视频合成逻辑"""
        try:
            # 创建输出文件夹（如果不存在）
            os.makedirs(self.output_folder, exist_ok=True)
            
            for i in range(self.total_outputs):
                if not self.running or self._cancel_requested:
                    break
                
                # 选择视频文件
                selected_files = self.select_files()
                if len(selected_files) < self.videos_per_output:
                    self.process_finished.emit(f"错误：可用视频文件不足，无法完成第{i+1}个视频的合成")
                    return
                
                # 处理并合成视频
                try:
                    # 发射开始处理当前视频的进度
                    start_progress = i / self.total_outputs
                    self.detailed_progress_updated.emit(start_progress)
                    self.progress_updated.emit(int(start_progress * 100))
                    
                    self.process_and_merge(selected_files, i+1)
                except Exception as e:
                    if not self._cancel_requested:
                        self.process_finished.emit(f"合成第{i+1}个视频时出错：{str(e)}")
                    continue
                
                # 更新进度（视频完成）
                if not self._cancel_requested:
                    progress = int((i + 1) / self.total_outputs * 100)
                    detailed_progress = (i + 1) / self.total_outputs
                    
                    self.progress_updated.emit(progress)
                    self.detailed_progress_updated.emit(detailed_progress)
                    
                    # 调试输出
                    print(f"视频 {i + 1}/{self.total_outputs} 完成, 进度: {progress}%")
            
            if self.running and not self._cancel_requested:
                
                # 确保进度条显示100%
                self.progress_updated.emit(100)
                self.detailed_progress_updated.emit(1.0)
                self.process_finished.emit("所有视频合成完成！")
            else:
                self.process_finished.emit("操作已取消")
        except Exception as e:
            if not self._cancel_requested:
                self.process_finished.emit(f"发生错误：{str(e)}")
    
    def select_files(self):
        """
        选择要合成的视频文件
        
        优先使用 SequenceDiversitySelector 进行智能选择，
        确保顺序完全不重复且连续2元素顺序也不重复。
        如果检测到分割片段，则增加去重逻辑确保同一原视频的片段不会同时出现。
        如果不允许重复使用素材，则回退到传统模式。
        """
        if self.reuse_material:
            # 允许重复使用素材，使用智能选择器
            if self.has_split_segments:
                # 如果有分割片段，先用去重逻辑过滤可用片段
                available_segments = SegmentDeduplicator.filter_segments_for_dedup(
                    [os.path.join(self.input_folder, f) for f in self.video_files], 
                    self.videos_per_output
                )
                # 转换回相对路径并使用智能选择器
                available_basenames = [os.path.basename(seg) for seg in available_segments]
                
                if len(available_basenames) < self.videos_per_output:
                    # 如果去重后素材不够，回退到普通选择
                    print(f"去重后素材不足({len(available_basenames)}<{self.videos_per_output})，使用普通选择")
                    selected = self.sequence_selector.get_next_combination()
                else:
                    # 从去重后的片段中进行智能选择
                    # 关键修复：继续使用同一 selector 以保持持久化记录
                    selected = self.sequence_selector.get_next_combination_from_allowed(available_basenames)
            else:
                # 没有分割片段，使用普通智能选择
                selected = self.sequence_selector.get_next_combination()
            
            return selected
        else:
            # 不允许重复使用素材，使用传统模式
            return self._select_files_traditional()
    
    def _select_files_traditional(self):
        """传统的文件选择方式（不重复使用素材）"""
        available_files = [f for f in self.video_files if f not in self.used_files]
        
        # 如果可用文件不足，重置已使用文件
        if len(available_files) < self.videos_per_output:
            self.used_files.clear()
            available_files = self.video_files.copy()
        
        # 如果有分割片段，应用去重逻辑
        if self.has_split_segments:
            # 转换为完整路径进行去重过滤
            available_segments = [os.path.join(self.input_folder, f) for f in available_files]
            filtered_segments = SegmentDeduplicator.filter_segments_for_dedup(
                available_segments, self.videos_per_output
            )
            
            if len(filtered_segments) >= self.videos_per_output:
                # 去重后有足够素材，使用去重后的结果
                selected_paths = random.sample(filtered_segments, self.videos_per_output)
                selected = [os.path.basename(path) for path in selected_paths]
            else:
                # 去重后素材不足，使用普通随机选择
                selected = random.sample(available_files, self.videos_per_output)
        else:
            # 没有分割片段，使用普通随机选择
            selected = random.sample(available_files, self.videos_per_output)
        
        # 标记为已使用
        for f in selected:
            self.used_files.add(f)
        
        return selected
    
    def process_and_merge(self, selected_files, output_number):
        """处理视频（转码）并合成为一个视频，包含音频处理"""
        # 检查取消状态
        if self._cancel_requested:
            return
        
        clips = []
        
        # 处理每个视频
        for i, file in enumerate(selected_files):
            # 检查取消状态
            if self._cancel_requested:
                # 关闭已打开的剪辑
                for c in clips:
                    c.close()
                return
                
            file_path = os.path.join(self.input_folder, file)
            
            try:
                # 读取视频
                clip = VideoFileClip(file_path)
                
                # 如果不保留原音频，并且没有替换音频或背景音频，则移除原音频
                # 如果有替换音频或背景音频，原音频会在后续的FFmpeg处理中被处理
                has_replace_audio = (self.audio_settings.get('replace_audio', False) and 
                                   self.audio_settings.get('replace_audio_path', ''))
                has_background_audio = (self.audio_settings.get('background_audio', False) and 
                                      self.audio_settings.get('background_audio_path', ''))
                
                if not self.audio_settings['keep_original'] and not has_replace_audio and not has_background_audio:
                    clip = clip.without_audio()
                    print(f"[VideoProcessor] 移除文件 {file} 的原音频（无其他音频源）")
                elif not self.audio_settings['keep_original']:
                    print(f"[VideoProcessor] 保留文件 {file} 的原音频用于后续处理（有替换音频或背景音频）")
                
                # 调整分辨率
                width, height = map(int, self.resolution.split('x'))
                resized_clip = clip.resize((width, height))
                
                clips.append(resized_clip)
                
                # 发射单个视频处理进度
                video_progress = (i + 1) / len(selected_files) * 0.8  # 视频处理占80%
                base_progress = (output_number - 1) / self.total_outputs
                current_video_progress = video_progress / self.total_outputs
                total_progress = base_progress + current_video_progress
                
                self.detailed_progress_updated.emit(total_progress)
                # 同时发射整数进度
                self.progress_updated.emit(int(total_progress * 100))
                
            except Exception as e:
                # 关闭已打开的剪辑
                for c in clips:
                    c.close()
                raise Exception(f"处理文件 {file} 时出错: {str(e)}")
        
        # 检查取消状态
        if self._cancel_requested:
            for c in clips:
                c.close()
            return
            
        # 合成视频
        final_clip = concatenate_videoclips(clips)
        
        # 更新进度：合成完成占85%
        base_progress = (output_number - 1) / self.total_outputs
        current_merge_progress = 0.85 / self.total_outputs
        total_progress = base_progress + current_merge_progress
        
        self.detailed_progress_updated.emit(total_progress)
        self.progress_updated.emit(int(total_progress * 100))

        # 检查取消状态
        if self._cancel_requested:
            final_clip.close()
            for c in clips:
                c.close()
            return

        # 获取最终视频的总时长
        final_video_duration = final_clip.duration

        # 输出文件路径 - 使用智能命名避免覆盖
        output_path = generate_unique_filename(self.output_folder, f"merged_{output_number:03d}", "mp4")
        
        # 检查是否需要复杂音频处理
        has_replace_audio = (self.audio_settings.get('replace_audio', False) and 
                           self.audio_settings.get('replace_audio_path', ''))
        has_background_audio = (self.audio_settings.get('background_audio', False) and 
                              self.audio_settings.get('background_audio_path', ''))
        
        if has_replace_audio or has_background_audio:
            # 使用FFmpeg进行复杂音频处理，避免MoviePy的文件占用问题
            print(f"[VideoProcessor] 使用FFmpeg处理复杂音频：替换音频={has_replace_audio}, 背景音频={has_background_audio}")
            self._process_with_ffmpeg_audio(selected_files, output_path, final_video_duration)
        else:
            # 简单情况：使用MoviePy直接写入（保持原音频或无音频）
            print(f"[VideoProcessor] 使用MoviePy进行简单处理，保留原音频={self.audio_settings['keep_original']}")
            final_clip.write_videofile(
                output_path,
                bitrate=self.bitrate,
                codec="libx264",
                audio_codec="aac",
                fps=30,
                verbose=False,
                logger=None
            )
        
        # 关闭所有剪辑释放资源
        for clip in clips:
            clip.close()
        final_clip.close()
        
        # 更新进度：处理完成
        base_progress = (output_number - 1) / self.total_outputs
        final_progress = base_progress + (1.0 / self.total_outputs)
        
        self.detailed_progress_updated.emit(final_progress)
        self.progress_updated.emit(int(final_progress * 100))

    def get_selection_statistics(self):
        """
        获取素材选择统计信息
        
        Returns:
            dict: 包含选择器统计信息的字典
        """
        if hasattr(self, 'sequence_selector'):
            stats = self.sequence_selector.get_statistics()
            stats['selection_mode'] = 'smart' if self.reuse_material else 'traditional'
            return stats
        else:
            return {
                'selection_mode': 'traditional',
                'used_files_count': len(self.used_files),
                'total_files': len(self.video_files)
            }

    def reset_selection_state(self):
        """重置选择状态"""
        if hasattr(self, 'sequence_selector'):
            self.sequence_selector.reset()
        self.used_files.clear()

    def stop(self):
        """停止处理线程"""
        self.running = False
        self._cancel_requested = True
        self.wait()
    
    def _process_with_ffmpeg_audio(self, selected_files: list, output_path: str, video_duration: float):
        """
        使用FFmpeg进行复杂音频处理
        
        Args:
            selected_files: 选中的视频文件列表
            output_path: 输出文件路径
            video_duration: 视频总时长
        """
        try:
            # 验证输入文件
            for video_file in selected_files:
                video_path = os.path.join(self.input_folder, video_file)
                if not os.path.exists(video_path):
                    raise Exception(f"视频文件不存在: {video_file}")
                if not os.access(video_path, os.R_OK):
                    raise Exception(f"视频文件不可读: {video_file}")
            
            print(f"[VideoProcessor] 验证通过，开始处理 {len(selected_files)} 个视频文件")
            
            # 检查是否有原音频可用
            has_original_audio = self.audio_settings['keep_original']
            
            # 获取包含原音频处理的滤镜链
            audio_inputs, audio_filter = self.audio_processor.build_audio_filter_with_original(
                video_duration, has_original_audio
            )
            
            if not audio_filter:
                # 没有音频处理，回退到简单方式
                print(f"[VideoProcessor] 没有音频滤镜，回退到MoviePy处理")
                return
            
            # 构建FFmpeg命令
            cmd = ['ffmpeg', '-y']  # -y 覆盖输出文件
            
            # 添加视频输入
            video_count = len(selected_files)
            for video_file in selected_files:
                video_path = os.path.join(self.input_folder, video_file)
                cmd.extend(['-i', video_path])
            
            # 添加音频输入
            for audio_file in audio_inputs:
                cmd.extend(['-i', audio_file])
            
            # 调整音频滤镜中的输入索引
            # 将占位符替换为实际的输入索引
            adjusted_audio_filter = audio_filter
            for i, _ in enumerate(audio_inputs):
                placeholder = f"AUDIO_INPUT_{i+1}"
                actual_index = video_count + i  # 音频输入在视频输入之后
                adjusted_audio_filter = adjusted_audio_filter.replace(placeholder, str(actual_index))
            
            # 读取目标分辨率（用于统一缩放与SAR）
            try:
                target_width, target_height = map(int, self.resolution.split('x'))
            except Exception:
                # 回退到常见分辨率以避免崩溃
                target_width, target_height = 1080, 1920

            # 视频处理：预缩放并合并视频流，统一 SAR=1
            if video_count > 1:
                # 多个视频需要合并
                # 检查是否需要保留原音频用于混合
                scale_chains = []
                scaled_labels = []
                for idx in range(video_count):
                    label = f"v{idx}"
                    scaled_labels.append(f"[{label}]")
                    # 对每个输入先缩放并将 SAR 设为 1
                    scale_chains.append(f"[{idx}:v]scale={target_width}:{target_height},setsar=1[{label}]")

                concat_inputs = ''.join(scaled_labels)
                if not self.audio_settings['keep_original']:
                    # 不保留原音频，只合并视频流
                    video_filter = f"{';'.join(scale_chains)};{concat_inputs}concat=n={video_count}:v=1:a=0[vout]"
                else:
                    # 保留原音频，合并视频与原音频
                    video_filter = f"{';'.join(scale_chains)};{concat_inputs}concat=n={video_count}:v=1:a=1[vout][orig_audio]"
            else:
                # 单个视频
                if not self.audio_settings['keep_original']:
                    # 不保留原音频，缩放并设定 SAR 后输出
                    video_filter = f"[0:v]scale={target_width}:{target_height},setsar=1[vout]"
                else:
                    # 保留原音频，缩放视频并直通原音频
                    video_filter = f"[0:v]scale={target_width}:{target_height},setsar=1[vout];[0:a]anull[orig_audio]"
            
            # 构建完整滤镜链
            if adjusted_audio_filter:
                complete_filter = f"{video_filter};{adjusted_audio_filter}"
                cmd.extend(['-filter_complex', complete_filter])
                cmd.extend(['-map', '[vout]', '-map', '[aout]'])
                print(f"[VideoProcessor] 使用复杂滤镜链：{complete_filter}")
            else:
                # 只有视频处理，没有音频
                cmd.extend(['-filter_complex', video_filter])
                cmd.extend(['-map', '[vout]'])
                print(f"[VideoProcessor] 只使用视频滤镜：{video_filter}")
            
            # 编码参数
            cmd.extend([
                '-c:v', 'libx264',
                '-b:v', self.bitrate,
                '-c:a', 'aac',
                '-r', '30'
            ])
            
            # 输出文件
            cmd.append(output_path)
            
            print(f"[VideoProcessor] 执行FFmpeg命令: {' '.join(cmd)}")
            
            # 执行FFmpeg命令，保留详细输出
            print(f"[VideoProcessor] 开始执行FFmpeg处理...")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,  # 5分钟超时
                encoding='utf-8',
                errors='ignore'
            )
            
            # 显示FFmpeg的详细输出
            if result.stdout:
                print(f"[VideoProcessor] FFmpeg标准输出:")
                print(result.stdout)
            
            if result.stderr:
                print(f"[VideoProcessor] FFmpeg错误输出:")
                print(result.stderr)
            
            if result.returncode != 0:
                print(f"[VideoProcessor] FFmpeg命令失败，返回码: {result.returncode}")
                print(f"[VideoProcessor] 执行的命令: {' '.join(cmd)}")
                print(f"[VideoProcessor] 输入文件: {selected_files}")
                print(f"[VideoProcessor] 音频输入: {audio_inputs}")
                print(f"[VideoProcessor] 完整错误信息: {result.stderr}")
                
                # 分析常见错误
                if "No such file or directory" in result.stderr:
                    raise Exception(f"文件不存在或路径错误: {result.stderr}")
                elif "Invalid data found" in result.stderr or "moov atom not found" in result.stderr:
                    raise Exception(f"输入文件格式无效或损坏: {result.stderr}")
                elif "does not contain any stream" in result.stderr:
                    raise Exception(f"输入文件不包含有效的音视频流: {result.stderr}")
                else:
                    raise Exception(f"FFmpeg处理失败: {result.stderr}")
            
            print(f"[VideoProcessor] FFmpeg处理成功: {output_path}")
            
            # 验证输出文件
            if os.path.exists(output_path):
                file_size = os.path.getsize(output_path)
                print(f"[VideoProcessor] 输出文件大小: {file_size} 字节")
                
                # 检查音频流
                try:
                    probe_cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_streams', output_path]
                    probe_result = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=30)
                    if probe_result.returncode == 0:
                        import json
                        streams = json.loads(probe_result.stdout)['streams']
                        audio_streams = [s for s in streams if s['codec_type'] == 'audio']
                        video_streams = [s for s in streams if s['codec_type'] == 'video']
                        print(f"[VideoProcessor] 输出文件包含 {len(video_streams)} 个视频流, {len(audio_streams)} 个音频流")
                        if audio_streams:
                            audio_stream = audio_streams[0]
                            print(f"[VideoProcessor] 音频流信息: {audio_stream['codec_name']}, {audio_stream.get('sample_rate', 'unknown')}Hz, {audio_stream.get('channels', 'unknown')}声道")
                except Exception as probe_error:
                    print(f"[VideoProcessor] 无法检查输出文件信息: {probe_error}")
            else:
                print(f"[VideoProcessor] 警告: 输出文件不存在: {output_path}")
            
        except Exception as e:
            print(f"[VideoProcessor] FFmpeg音频处理失败: {e}")
            # 回退到简单的MoviePy处理
            raise e
    

