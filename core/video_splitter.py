"""
视频分割器模块

支持将视频按随机时长分割，可处理单个文件或整个文件夹，
支持码率、分辨率设置，跳过不满足最小时长的片段
"""

import os
import random
import time
import subprocess
import logging
from datetime import datetime
from PyQt5.QtCore import QThread, pyqtSignal
from moviepy.editor import VideoFileClip
from .resource_manager import ResourceManager, managed_video_clip, force_cleanup_file_handles
import json


class VideoSplitter(QThread):
    """视频分割器线程，支持文件夹批量处理"""
    progress_updated = pyqtSignal(int)
    process_finished = pyqtSignal(str)
    detailed_progress_updated = pyqtSignal(float)
    
    def __init__(self, input_path, output_folder, split_duration_range, 
                 resolution=None, bitrate=None, use_gpu=False, quality="high", save_metadata=True, delete_original=False):
        """
        初始化视频分割器
        
        Args:
            input_path: 输入路径（文件或文件夹）
            output_folder: 输出文件夹
            split_duration_range: 分割时长范围 (min_seconds, max_seconds)
            resolution: 输出分辨率 "1920x1080" 或 None（保持原分辨率）
            bitrate: 输出码率 "5000k" 或 None（自动设置）
            use_gpu: 是否使用GPU加速
            quality: 编码质量 "high"/"medium"/"low"
            save_metadata: 是否保存元数据用于去重
            delete_original: 是否删除原视频文件
        """
        super().__init__()
        self.input_path = input_path
        self.output_folder = output_folder
        self.min_duration, self.max_duration = split_duration_range
        self.resolution = resolution
        self.bitrate = bitrate
        self.use_gpu = use_gpu
        self.quality = quality
        self.save_metadata = save_metadata
        self.delete_original = delete_original
        
        self.running = True
        self._cancel_requested = False
        
        # 资源管理器
        self.resource_manager = ResourceManager()
        
        # 支持的视频格式
        self.video_extensions = ('.mp4', '.avi', '.mov', '.mkv', '.flv', '.wmv', '.mpeg', '.mpg')
        
        # 获取要处理的视频文件列表
        self.video_files = self._get_video_files()
        if not self.video_files:
            raise ValueError("没有找到可处理的视频文件")
        
        # 跟踪成功处理的文件（用于删除原文件）
        self.successfully_processed_files = []
        
        # 设置日志记录
        self.logger = self._setup_logger()
    
    def _setup_logger(self):
        """设置详细的日志记录器（仅控制台输出）"""
        logger = logging.getLogger(f'VideoSplitter_{id(self)}')
        logger.setLevel(logging.DEBUG)
        
        # 避免重复添加handler
        if logger.handlers:
            logger.handlers.clear()
        
        # 只创建console handler，不再创建文件handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG)
        
        # 创建formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        
        return logger
    
    def _get_video_files(self):
        """获取要处理的视频文件列表"""
        video_files = []
        
        if os.path.isfile(self.input_path):
            # 单个文件
            if self.input_path.lower().endswith(self.video_extensions):
                video_files.append(self.input_path)
        elif os.path.isdir(self.input_path):
            # 文件夹
            for file in os.listdir(self.input_path):
                if file.lower().endswith(self.video_extensions):
                    video_files.append(os.path.join(self.input_path, file))
        
        return video_files
    
    def run(self):
        """线程运行函数"""
        try:
            self.logger.info("=== 视频分割器开始运行 ===")
            self.logger.info(f"输入路径: {self.input_path}")
            self.logger.info(f"输出文件夹: {self.output_folder}")
            self.logger.info(f"分割时长范围: {self.min_duration}-{self.max_duration}秒")
            self.logger.info(f"分辨率设置: {self.resolution}")
            self.logger.info(f"码率设置: {self.bitrate}")
            self.logger.info(f"使用GPU: {self.use_gpu}")
            self.logger.info(f"编码质量: {self.quality}")
            self.logger.info(f"保存元数据: {self.save_metadata}")
            self.logger.info(f"删除原视频: {self.delete_original}")
            
            # 创建输出文件夹
            os.makedirs(self.output_folder, exist_ok=True)
            
            total_files = len(self.video_files)
            total_segments_created = 0
            
            self.logger.info(f"找到 {total_files} 个视频文件待处理:")
            for i, video_file in enumerate(self.video_files):
                self.logger.info(f"  {i+1}. {os.path.basename(video_file)}")
            
            for file_index, video_file in enumerate(self.video_files):
                if not self.running or self._cancel_requested:
                    self.logger.warning("处理被取消")
                    break
                
                self.logger.info(f"\n--- 处理第 {file_index + 1}/{total_files} 个文件 ---")
                self.logger.info(f"当前处理: {os.path.basename(video_file)}")
                self.logger.info(f"文件路径: {video_file}")
                
                try:
                    segments_count = self._split_video(video_file, file_index + 1)
                    total_segments_created += segments_count
                    self.logger.info(f"分割结果: 生成 {segments_count} 个片段")
                    
                    if segments_count == 0:
                        self.logger.warning(f"文件分割失败，未生成任何片段: {os.path.basename(video_file)}")
                    
                    # 更新总体进度
                    progress = int((file_index + 1) / total_files * 100)
                    detailed_progress = (file_index + 1) / total_files
                    
                    self.progress_updated.emit(progress)
                    self.detailed_progress_updated.emit(detailed_progress)
                    
                    # 调试输出
                    print(f"分割文件 {file_index + 1}/{total_files} 完成, 进度: {progress}%")
                    
                except Exception as e:
                    if not self._cancel_requested:
                        print(f"处理视频 {video_file} 时出错: {str(e)}")
                        continue
            
            if self.running and not self._cancel_requested:
                # 确保进度条显示100%
                print("[VideoSplitter] 发射100%进度信号")
                self.progress_updated.emit(100)
                self.detailed_progress_updated.emit(1.0)
                
                # 强制清理资源，确保文件句柄释放
                print("[VideoSplitter] 开始清理资源...")
                self.resource_manager.cleanup_all()
                force_cleanup_file_handles()
                
                self.logger.info(f"\n=== 处理完成统计 ===")
                self.logger.info(f"总文件数: {total_files}")
                self.logger.info(f"生成片段数: {total_segments_created}")
                self.logger.info(f"成功处理的文件数: {len(self.successfully_processed_files)}")
                self.logger.info(f"删除原视频选项: {self.delete_original}")
                
                # 删除原视频文件（如果启用）
                if self.delete_original:
                    self.logger.info(f"开始执行删除原视频文件操作...")
                    if self.successfully_processed_files:
                        self.logger.info(f"准备删除 {len(self.successfully_processed_files)} 个成功处理的文件:")
                        for i, file_path in enumerate(self.successfully_processed_files):
                            self.logger.info(f"  {i+1}. {os.path.basename(file_path)}")
                        
                        deleted_count = self._delete_original_files()
                        self.logger.info(f"删除操作完成，共删除 {deleted_count} 个文件")
                        self.process_finished.emit(f"分割完成！共处理 {total_files} 个视频文件，生成 {total_segments_created} 个片段，删除 {deleted_count} 个原文件")
                    else:
                        self.logger.warning("没有成功处理的文件可供删除")
                        self.process_finished.emit(f"分割完成！共处理 {total_files} 个视频文件，生成 {total_segments_created} 个片段（无文件被删除）")
                else:
                    self.logger.info("删除原视频选项未启用，保留所有原文件")
                    self.process_finished.emit(f"分割完成！共处理 {total_files} 个视频文件，生成 {total_segments_created} 个片段")
            else:
                self.logger.warning("操作被取消")
                self.process_finished.emit("操作已取消")
                
        except Exception as e:
            if not self._cancel_requested:
                self.process_finished.emit(f"分割过程中发生错误：{str(e)}")
    
    def _split_video(self, video_file, file_number):
        """分割单个视频文件"""
        if self._cancel_requested:
            self.logger.warning("分割操作被取消")
            return 0
            
        self.logger.info(f"开始分割视频: {os.path.basename(video_file)}")
        
        # 获取视频信息
        try:
            total_duration = self._get_video_duration(video_file)
            self.logger.info(f"视频总时长: {total_duration:.1f}秒")
            
            if total_duration < self.min_duration:
                self.logger.warning(f"视频时长 {total_duration:.1f}秒 小于最小分割时长 {self.min_duration}秒，跳过")
                return 0
            
        except Exception as e:
            self.logger.error(f"无法获取视频信息: {str(e)}")
            return 0
        
        # 计算分割方案
        segments_info = self._calculate_split_segments(total_duration)
        base_name = os.path.splitext(os.path.basename(video_file))[0]
        
        self.logger.info(f"计算分割方案: 将生成 {len(segments_info)} 个片段")
        for i, (start_time, duration) in enumerate(segments_info):
            self.logger.debug(f"  片段 {i+1}: {start_time:.1f}s - {start_time + duration:.1f}s (时长: {duration:.1f}s)")
        
        segments_created = 0
        
        for segment_index, (start_time, segment_duration) in enumerate(segments_info):
            if self._cancel_requested:
                self.logger.warning("片段处理被取消")
                break
            
            self.logger.info(f"处理片段 {segment_index + 1}/{len(segments_info)}: {start_time:.1f}s-{start_time + segment_duration:.1f}s")
            
            # 生成输出文件名：原文件名-1, 原文件名-2
            output_filename = f"{base_name}-{segment_index + 1}.mp4"
            output_path = os.path.join(self.output_folder, output_filename)
            
            # 避免文件名冲突
            counter = 1
            original_output_filename = output_filename
            while os.path.exists(output_path):
                output_filename = f"{base_name}-{segment_index + 1}_{counter}.mp4"
                output_path = os.path.join(self.output_folder, output_filename)
                counter += 1
            
            if counter > 1:
                self.logger.info(f"文件名冲突，使用新名称: {output_filename}")
            
            self.logger.debug(f"输出路径: {output_path}")
            
            # 使用FFmpeg进行分割（支持GPU加速）
            try:
                if self.use_gpu:
                    self.logger.debug("使用GPU加速模式分割")
                    success = self._split_with_ffmpeg_gpu(video_file, output_path, start_time, segment_duration)
                else:
                    self.logger.debug("使用CPU模式分割")
                    success = self._split_with_ffmpeg_cpu(video_file, output_path, start_time, segment_duration)
                
                if success:
                    # 检查生成的文件
                    if os.path.exists(output_path):
                        file_size = os.path.getsize(output_path)
                        self.logger.info(f"✅ 片段分割成功: {output_filename} (大小: {file_size} 字节)")
                        
                        # 保存片段元数据（用于后续去重）
                        if self.save_metadata:
                            self.logger.debug("保存片段元数据")
                            self._save_segment_metadata(output_path, video_file, start_time, segment_duration)
                        segments_created += 1
                    else:
                        self.logger.error(f"❌ 片段文件未生成: {output_filename}")
                else:
                    self.logger.error(f"❌ 片段分割失败: {output_filename}")
                    
            except Exception as e:
                self.logger.error(f"❌ 分割片段时出错 {output_filename}: {str(e)}")
        
        # 如果成功分割出片段，添加到成功处理列表
        if segments_created > 0:
            if video_file not in self.successfully_processed_files:
                self.successfully_processed_files.append(video_file)
                self.logger.info(f"已将文件添加到成功处理列表: {os.path.basename(video_file)}")
        
        return segments_created
    
    def _calculate_split_segments(self, total_duration):
        """计算分割方案"""
        segments = []
        current_time = 0.0
        
        while current_time < total_duration:
            # 随机生成分割时长
            segment_duration = random.uniform(self.min_duration, self.max_duration)
            
            # 检查剩余时长
            remaining_duration = total_duration - current_time
            
            if remaining_duration < self.min_duration:
                # 剩余时长不足最小时长，跳过
                break
            
            if remaining_duration < segment_duration:
                # 剩余时长小于随机时长，但大于最小时长，则使用剩余时长
                segment_duration = remaining_duration
            
            segments.append((current_time, segment_duration))
            current_time += segment_duration
        
        return segments
    
    def _get_video_duration(self, video_file):
        """使用FFmpeg获取视频时长"""
        cmd = [
            'ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format',
            video_file
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True, encoding='utf-8', errors='ignore')
            import json
            data = json.loads(result.stdout)
            return float(data['format']['duration'])
        except Exception:
            # 回退到MoviePy，使用资源管理器
            try:
                with managed_video_clip(video_file, self.resource_manager) as clip:
                    duration = clip.duration
                return duration
            except Exception as e:
                raise Exception(f"无法获取视频时长: {str(e)}")
    
    def _split_with_ffmpeg_gpu(self, input_file, output_file, start_time, duration):
        """使用FFmpeg GPU加速分割视频"""
        cmd = ['ffmpeg', '-y']  # -y 覆盖输出文件
        
        # GPU解码（如果支持）
        cmd.extend(['-hwaccel', 'auto'])
        
        # 输入文件和时间设置
        cmd.extend(['-ss', str(start_time)])
        cmd.extend(['-i', input_file])
        cmd.extend(['-t', str(duration)])
        
        # GPU编码设置
        if self.quality == "high":
            cmd.extend(['-c:v', 'h264_nvenc', '-preset', 'slow', '-crf', '18'])
        elif self.quality == "medium":
            cmd.extend(['-c:v', 'h264_nvenc', '-preset', 'medium', '-crf', '23'])
        else:  # fast
            cmd.extend(['-c:v', 'h264_nvenc', '-preset', 'fast', '-crf', '28'])
        
        # 分辨率设置
        if self.resolution:
            cmd.extend(['-vf', f'scale={self.resolution}'])
        
        # 码率设置
        if self.bitrate:
            cmd.extend(['-b:v', self.bitrate])
        
        # 音频设置
        cmd.extend(['-c:a', 'aac'])
        
        # 输出文件
        cmd.append(output_file)
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore')
            if result.returncode == 0:
                return True
            else:
                print(f"FFmpeg GPU错误: {result.stderr}")
                # 如果GPU失败，回退到CPU
                return self._split_with_ffmpeg_cpu(input_file, output_file, start_time, duration)
        except Exception as e:
            print(f"FFmpeg GPU分割失败: {str(e)}")
            return self._split_with_ffmpeg_cpu(input_file, output_file, start_time, duration)
    
    def _split_with_ffmpeg_cpu(self, input_file, output_file, start_time, duration):
        """使用FFmpeg CPU分割视频"""
        cmd = ['ffmpeg', '-y']  # -y 覆盖输出文件
        
        # 输入文件和时间设置
        cmd.extend(['-ss', str(start_time)])
        cmd.extend(['-i', input_file])
        cmd.extend(['-t', str(duration)])
        
        # CPU编码设置
        cmd.extend(['-c:v', 'libx264'])
        
        if self.quality == "high":
            cmd.extend(['-preset', 'slow', '-crf', '18'])
        elif self.quality == "medium":
            cmd.extend(['-preset', 'medium', '-crf', '23'])
        else:  # fast
            cmd.extend(['-preset', 'fast', '-crf', '28'])
        
        # 分辨率设置
        if self.resolution:
            cmd.extend(['-vf', f'scale={self.resolution}'])
        
        # 码率设置
        if self.bitrate:
            cmd.extend(['-b:v', self.bitrate])
        
        # 音频设置
        cmd.extend(['-c:a', 'aac'])
        
        # 输出文件
        cmd.append(output_file)
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore')
            return result.returncode == 0
        except Exception as e:
            print(f"FFmpeg CPU分割失败: {str(e)}")
            return False
    
    def _get_codec_params(self):
        """获取编码参数"""
        params = {
            'codec': 'libx264',
            'audio_codec': 'aac'
        }
        
        if self.bitrate:
            params['bitrate'] = self.bitrate
        
        # 根据质量设置，使用更简单的参数
        if self.quality == "high":
            # 高质量：低压缩率
            if not self.bitrate:
                params['bitrate'] = '8000k'
        elif self.quality == "medium":
            # 中等质量：平衡压缩
            if not self.bitrate:
                params['bitrate'] = '5000k'
        else:  # low/fast
            # 快速编码：高压缩率
            if not self.bitrate:
                params['bitrate'] = '3000k'
        
        return params
    
    def _save_segment_metadata(self, segment_path, source_video, start_time, duration):
        """保存片段元数据到统一的元数据文件"""
        metadata = {
            'segment_file': os.path.basename(segment_path),
            'source_video': os.path.abspath(source_video),
            'source_basename': os.path.basename(source_video),
            'start_time': start_time,
            'duration': duration,
            'created_time': datetime.now().isoformat()
        }
        
        # 统一的元数据文件路径
        metadata_file = os.path.join(self.output_folder, 'segments_metadata.json')
        
        try:
            # 读取现有元数据
            all_metadata = []
            if os.path.exists(metadata_file):
                with open(metadata_file, 'r', encoding='utf-8') as f:
                    all_metadata = json.load(f)
            
            # 添加新的元数据
            all_metadata.append(metadata)
            
            # 保存回文件
            with open(metadata_file, 'w', encoding='utf-8') as f:
                json.dump(all_metadata, f, ensure_ascii=False, indent=2)
                
        except Exception as e:
            print(f"保存元数据失败: {str(e)}")
    
    def _delete_original_files(self):
        """删除成功处理的原视频文件"""
        self.logger.info("=== 开始删除原视频文件 ===")
        deleted_count = 0
        failed_files = []
        
        for i, video_file in enumerate(self.successfully_processed_files):
            self.logger.info(f"处理第 {i+1}/{len(self.successfully_processed_files)} 个文件: {os.path.basename(video_file)}")
            self.logger.debug(f"完整路径: {video_file}")
            
            try:
                if os.path.exists(video_file):
                    # 检查文件大小和修改时间
                    file_size = os.path.getsize(video_file)
                    file_mtime = os.path.getmtime(video_file)
                    self.logger.debug(f"文件大小: {file_size} 字节")
                    self.logger.debug(f"文件修改时间: {datetime.fromtimestamp(file_mtime)}")
                    
                    # 执行删除
                    os.remove(video_file)
                    deleted_count += 1
                    self.logger.info(f"✅ 成功删除: {os.path.basename(video_file)}")
                else:
                    self.logger.warning(f"❌ 文件不存在，跳过删除: {os.path.basename(video_file)}")
            except PermissionError as e:
                failed_files.append(os.path.basename(video_file))
                self.logger.error(f"❌ 权限不足，删除失败 {os.path.basename(video_file)}: {str(e)}")
            except Exception as e:
                failed_files.append(os.path.basename(video_file))
                self.logger.error(f"❌ 删除失败 {os.path.basename(video_file)}: {str(e)}")
        
        if failed_files:
            self.logger.warning(f"以下 {len(failed_files)} 个文件删除失败: {', '.join(failed_files)}")
        
        self.logger.info(f"删除操作统计: 成功 {deleted_count} 个，失败 {len(failed_files)} 个")
        return deleted_count
    
    def stop(self):
        """停止处理"""
        self.running = False
        self._cancel_requested = True
        
        # 清理所有资源
        if hasattr(self, 'resource_manager'):
            print("[VideoSplitter] 停止时清理资源...")
            self.resource_manager.cleanup_all(force=True)
            force_cleanup_file_handles()
        
        # 清理日志句柄
        if hasattr(self, 'logger') and self.logger:
            self.logger.handlers.clear()
        self.wait()


class SegmentDeduplicator:
    """片段去重器 - 确保同一原视频的片段不会同时出现在一个合成视频中"""
    
    @staticmethod
    def load_segments_metadata(folder_path):
        """加载文件夹中的统一元数据文件"""
        metadata_file = os.path.join(folder_path, 'segments_metadata.json')
        
        try:
            if os.path.exists(metadata_file):
                with open(metadata_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"加载元数据文件失败 {metadata_file}: {str(e)}")
        
        return []
    
    @staticmethod
    def get_source_video(segment_path):
        """获取片段的原视频文件路径"""
        folder_path = os.path.dirname(segment_path)
        segment_filename = os.path.basename(segment_path)
        
        # 先尝试从统一元数据文件中查找
        metadata_list = SegmentDeduplicator.load_segments_metadata(folder_path)
        for metadata in metadata_list:
            if metadata.get('segment_file') == segment_filename:
                return metadata.get('source_video') or metadata.get('source_basename')
        
        # 如果没有元数据，尝试从文件名推断
        # 格式: 原文件名-1.mp4, 原文件名-2.mp4
        if '-' in segment_filename and segment_filename.lower().endswith('.mp4'):
            # 移除片段编号后缀
            parts = segment_filename.rsplit('-', 1)
            if len(parts) == 2 and parts[1].replace('.mp4', '').isdigit():
                return parts[0]
        
        return segment_filename
    
    @staticmethod
    def filter_segments_for_dedup(available_segments, per_video):
        """
        为去重目的过滤片段列表
        确保选中的片段来自不同的原视频
        
        Args:
            available_segments: 可用片段列表
            per_video: 每个视频需要的片段数量
            
        Returns:
            filtered_segments: 过滤后的片段列表
        """
        # 按原视频分组
        source_groups = {}
        for segment in available_segments:
            source = SegmentDeduplicator.get_source_video(segment)
            if source not in source_groups:
                source_groups[source] = []
            source_groups[source].append(segment)
        
        # 从每个原视频组中最多选择一个片段
        selected_segments = []
        source_list = list(source_groups.keys())
        random.shuffle(source_list)  # 随机化原视频选择顺序
        
        for source in source_list:
            if len(selected_segments) >= per_video:
                break
            # 从该原视频的片段中随机选择一个
            segments_from_source = source_groups[source]
            selected_segment = random.choice(segments_from_source)
            selected_segments.append(selected_segment)
        
        return selected_segments


def get_split_segments_from_folder(folder_path):
    """
    从文件夹中获取所有分割的视频片段
    
    Returns:
        list: 分割片段文件路径列表
    """
    if not os.path.isdir(folder_path):
        return []
    
    video_extensions = ('.mp4', '.avi', '.mov', '.mkv', '.flv', '.wmv', '.mpeg', '.mpg')
    segments = []
    
    # 检查是否有统一的元数据文件
    metadata_file = os.path.join(folder_path, 'segments_metadata.json')
    has_metadata = os.path.exists(metadata_file)
    
    if has_metadata:
        # 如果有元数据文件，从中获取片段列表
        try:
            metadata_list = SegmentDeduplicator.load_segments_metadata(folder_path)
            for metadata in metadata_list:
                segment_file = metadata.get('segment_file')
                if segment_file:
                    segment_path = os.path.join(folder_path, segment_file)
                    if os.path.exists(segment_path):
                        segments.append(segment_path)
        except Exception as e:
            print(f"读取元数据文件出错: {str(e)}")
    
    # 如果没有元数据文件或读取失败，回退到文件名检测
    if not segments:
        for file in os.listdir(folder_path):
            if file.lower().endswith(video_extensions):
                # 检查是否符合分割片段命名规则：原文件名-数字.mp4
                if '-' in file and file.count('-') >= 1:
                    file_path = os.path.join(folder_path, file)
                    segments.append(file_path)
    
    return segments
