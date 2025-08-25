"""
FFmpeg GPU加速视频处理器

支持NVIDIA NVENC、Intel QSV、AMD AMF等硬件加速编码器
提供比MoviePy更高的性能和更低的内存占用
"""

import os
import re
import json
import subprocess
import tempfile
import threading
import time
from datetime import datetime
from PyQt5.QtCore import QThread, pyqtSignal, Qt
from .audio_processor import AudioProcessor
from .sequence_selector import SequenceDiversitySelector
from .process_controller import ProcessController, FFmpegProgressMonitor, FFmpegCommandBuilder
from .resource_manager import ResourceManager, managed_video_clip, force_cleanup_file_handles


def generate_unique_filename_ffmpeg(output_folder: str, base_name: str, extension: str = "mp4") -> str:
    """
    为FFmpeg处理器生成唯一的文件名，避免覆盖现有文件
    
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


class FFmpegGPUProcessor(QThread):
    """FFmpeg GPU加速视频处理线程"""
    progress_updated = pyqtSignal(int)
    process_finished = pyqtSignal(str)
    detailed_progress_updated = pyqtSignal(float)  # 详细进度信号 (0.0-1.0)
    
    def __init__(self, input_folder, output_folder, videos_per_output, total_outputs, 
                 resolution, bitrate, reuse_material, audio_settings, gpu_settings=None):
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
        
        # GPU加速设置
        self.gpu_settings = gpu_settings or self._detect_gpu_capabilities()
        
        # 获取所有视频文件
        self.video_extensions = ('.mp4', '.avi', '.mov', '.mkv', '.flv', '.wmv', '.mpeg', '.mpg')
        self.video_files = [f for f in os.listdir(input_folder) 
                           if f.lower().endswith(self.video_extensions)]
        if not self.video_files:
            raise ValueError("输入文件夹中没有找到视频文件")
        
        # 使用 SequenceDiversitySelector 进行智能素材选择（启用持久化）
        # 使用标准的持久化文件路径生成逻辑
        dummy_selector = SequenceDiversitySelector(["dummy"], 1)
        persistence_file = dummy_selector.get_persistence_file_path(input_folder)
        
        self.sequence_selector = SequenceDiversitySelector(self.video_files, videos_per_output, persistence_file)
        
        # 传统的素材使用记录（兼容模式，当不重用素材时使用）
        self.used_files = set()
        
        # 音频处理器
        self.audio_processor = AudioProcessor(audio_settings)
        
        # 资源管理器
        self.resource_manager = ResourceManager()
        
        # 进程控制器和进度监控器
        self.process_controller = ProcessController()
        self.progress_monitor = FFmpegProgressMonitor(self.process_controller)
        
        # 连接进度信号
        self.process_controller.progress_updated.connect(self._on_detailed_progress)
        self.process_controller.process_error.connect(self._on_process_error)
        
        # 取消状态
        self._cancel_requested = False
        self._current_video_index = 0
    
    def _detect_gpu_capabilities(self):
        """检测GPU硬件加速能力"""
        capabilities = {
            'hardware_encoder': None,
            'hardware_decoder': None,
            'preset': 'medium',
            'crf': 23,
            'use_gpu': False
        }
        
        try:
            # 检测NVIDIA GPU (NVENC)
            result = subprocess.run(['nvidia-smi'], capture_output=True, text=True)
            if result.returncode == 0:
                capabilities.update({
                    'hardware_encoder': 'h264_nvenc',
                    'hardware_decoder': 'h264_cuvid',
                    'preset': 'p4',  # NVENC preset
                    'use_gpu': True
                })
                return capabilities
        except FileNotFoundError:
            pass
        
        try:
            # 检测Intel QSV
            result = subprocess.run(['ffmpeg', '-hide_banner', '-encoders'], 
                                  capture_output=True, text=True)
            if 'h264_qsv' in result.stdout:
                capabilities.update({
                    'hardware_encoder': 'h264_qsv',
                    'hardware_decoder': 'h264_qsv',
                    'preset': 'medium',
                    'use_gpu': True
                })
                return capabilities
        except FileNotFoundError:
            pass
        
        # 默认使用CPU编码
        capabilities.update({
            'hardware_encoder': 'libx264',
            'hardware_decoder': None,
            'preset': 'medium',
            'use_gpu': False
        })
        
        return capabilities
    
    def run(self):
        """线程运行函数，处理视频合成逻辑"""
        try:
            # 重置进程控制器
            self.process_controller.reset()
            
            # 创建输出文件夹
            os.makedirs(self.output_folder, exist_ok=True)
            
            for i in range(self.total_outputs):
                if not self.running or self._cancel_requested or self.process_controller.is_cancelled():
                    break
                
                self._current_video_index = i + 1
                
                # 选择视频文件
                selected_files = self._select_files()
                if len(selected_files) < self.videos_per_output:
                    self.process_finished.emit(f"错误：可用视频文件不足，无法完成第{i+1}个视频的合成")
                    return
                
                # 处理并合成视频
                try:
                    self._process_and_merge_ffmpeg(selected_files, i+1)
                except Exception as e:
                    if not self.process_controller.is_cancelled():
                        self.process_finished.emit(f"合成第{i+1}个视频时出错：{str(e)}")
                    continue
                
                # 更新总体进度
                if not self.process_controller.is_cancelled():
                    progress = int((i + 1) / self.total_outputs * 100)
                    self.progress_updated.emit(progress)
            
            if self.running and not self.process_controller.is_cancelled():
                # 确保进度条显示100%
                # 清理资源
                print("[FFmpegGPUProcessor] 处理完成，清理资源...")
                self.resource_manager.cleanup_all()
                force_cleanup_file_handles()
                
                self.progress_updated.emit(100)
                self.detailed_progress_updated.emit(1.0)
                self.process_finished.emit("所有视频合成完成！")
            else:
                self.process_finished.emit("操作已取消")
        except Exception as e:
            if not self.process_controller.is_cancelled():
                self.process_finished.emit(f"发生错误：{str(e)}")
    
    def _select_files(self):
        """
        选择要合成的视频文件
        
        优先使用 SequenceDiversitySelector 进行智能选择，
        确保顺序完全不重复且连续2元素顺序也不重复。
        如果不允许重复使用素材，则回退到传统模式。
        """
        if self.reuse_material:
            # 允许重复使用素材，使用智能选择器
            selected = self.sequence_selector.get_next_combination()
            return selected
        else:
            # 不允许重复使用素材，使用传统模式
            return self._select_files_traditional()
    
    def _select_files_traditional(self):
        """传统的文件选择方式（不重复使用素材）"""
        import random
        
        available_files = [f for f in self.video_files if f not in self.used_files]
        
        # 如果可用文件不足，重置已使用文件
        if len(available_files) < self.videos_per_output:
            self.used_files.clear()
            available_files = self.video_files.copy()
        
        # 随机选择视频
        selected = random.sample(available_files, self.videos_per_output)
        
        # 标记为已使用
        for f in selected:
            self.used_files.add(f)
        
        return selected
    
    def _process_and_merge_ffmpeg(self, selected_files, output_number):
        """使用FFmpeg GPU加速处理和合成视频"""
        # 使用智能命名避免覆盖现有文件
        output_path = generate_unique_filename_ffmpeg(self.output_folder, f"merged_{output_number:03d}", "mp4")
        
        # 检查取消状态
        if self.process_controller.is_cancelled():
            return
        
        # 检查是否需要复杂音频处理
        needs_complex_audio = (
            self.audio_settings.get('replace_audio', False) or 
            self.audio_settings.get('background_audio', False)
        )
        
        if needs_complex_audio:
            # 如果需要复杂音频处理，使用两步法：先合并视频，再处理音频
            self._process_with_complex_audio(selected_files, output_path)
        else:
            # 简单音频处理，直接使用FFmpeg
            concat_file = FFmpegCommandBuilder.create_concat_file(selected_files, self.input_folder)
            try:
                # 添加到临时文件列表
                temp_files = [concat_file]
                
                # 获取总时长
                total_duration = self.progress_monitor.get_total_duration_from_concat(concat_file)
                
                # 构建命令
                cmd = self._build_ffmpeg_command_with_progress(concat_file, output_path)
                
                # 执行FFmpeg
                self._execute_ffmpeg_with_progress_pipe(cmd, total_duration, output_path, temp_files)
                
            finally:
                # 清理临时文件（如果没有被进程控制器管理）
                if os.path.exists(concat_file) and not self.process_controller.is_cancelled():
                    try:
                        os.unlink(concat_file)
                    except Exception:
                        pass
    
    def _process_with_complex_audio(self, selected_files, output_path):
        """处理复杂音频情况（替换音频、背景音等）"""
        # 检查取消状态
        if self.process_controller.is_cancelled():
            return
            
        # 创建临时视频文件（无音频或仅原音频）
        temp_video_path = output_path.replace('.mp4', '_temp_video.mp4')
        concat_file = FFmpegCommandBuilder.create_concat_file(selected_files, self.input_folder)
        temp_files = [concat_file, temp_video_path]
        
        try:
            # 第一步：合并视频
            cmd = self._build_ffmpeg_command(concat_file, temp_video_path)
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            
            # 添加到进程控制器
            self.process_controller.add_process(process, temp_files, output_path)
            
            stdout, stderr = process.communicate()
            
            # 从进程控制器移除
            self.process_controller.remove_process(process)
            
            if process.returncode != 0 and not self.process_controller.is_cancelled():
                raise Exception(f"视频合并失败: {stderr}")
            
            # 检查取消状态
            if self.process_controller.is_cancelled():
                return
            
            # 第二步：使用MoviePy处理音频
            from moviepy.editor import VideoFileClip
            with managed_video_clip(temp_video_path, self.resource_manager) as video_clip:
                # 处理最终音频
                final_audio = self.audio_processor.process_final_audio(video_clip.duration)
                if final_audio:
                    video_clip = video_clip.set_audio(final_audio)
                else:
                    video_clip = video_clip.without_audio()
                
                # 检查取消状态
                if self.process_controller.is_cancelled():
                    return
                
                # 输出最终文件
                video_clip.write_videofile(
                    output_path,
                    codec="libx264",
                    audio_codec="aac",
                    fps=30,
                    verbose=False,
                    logger=None
                )
            
        except Exception as e:
            # 确保清理进程
            if 'process' in locals():
                self.process_controller.remove_process(process)
            if not self.process_controller.is_cancelled():
                raise e
        finally:
            # 清理临时文件（如果没有被进程控制器管理）
            if not self.process_controller.is_cancelled():
                for temp_file in [concat_file, temp_video_path]:
                    try:
                        if os.path.exists(temp_file):
                            os.unlink(temp_file)
                    except Exception:
                        pass
    
    def _build_ffmpeg_command_with_progress(self, concat_file, output_path):
        """构建带进度监控的FFmpeg命令"""
        input_args = ['-f', 'concat', '-safe', '0', '-i', concat_file]
        
        video_settings = {
            'resolution': self.resolution,
            'bitrate': self.bitrate,
            'fps': 30,
            'preset': self.gpu_settings.get('preset', 'medium'),
            'crf': self.gpu_settings.get('crf', 23)
        }
        
        audio_settings = {
            'keep_original': self.audio_settings.get('keep_original', False),
            'volume': self.audio_settings.get('original_volume', 100)
        }
        
        return FFmpegCommandBuilder.build_progress_command(
            input_args, output_path, 
            self.gpu_settings, video_settings, audio_settings
        )
    
    def _build_ffmpeg_command(self, concat_file, output_path):
        """构建FFmpeg命令"""
        cmd = ['ffmpeg', '-y']  # -y 覆盖输出文件
        
        # 硬件解码器（如果支持）
        if self.gpu_settings['hardware_decoder']:
            cmd.extend(['-hwaccel', 'cuda' if 'nvenc' in self.gpu_settings['hardware_encoder'] else 'auto'])
        
        # 输入文件
        cmd.extend(['-f', 'concat', '-safe', '0', '-i', concat_file])
        
        # 视频编码设置
        cmd.extend(['-c:v', self.gpu_settings['hardware_encoder']])
        
        # 编码器特定设置
        if 'nvenc' in self.gpu_settings['hardware_encoder']:
            # NVIDIA NVENC设置
            cmd.extend([
                '-preset', self.gpu_settings['preset'],
                '-rc', 'vbr',  # 可变比特率
                '-cq', '23',   # 质量设置
                '-b:v', self.bitrate,
                '-maxrate', str(int(self.bitrate.rstrip('k')) * 2) + 'k',
                '-bufsize', str(int(self.bitrate.rstrip('k')) * 2) + 'k'
            ])
        elif 'qsv' in self.gpu_settings['hardware_encoder']:
            # Intel QSV设置
            cmd.extend([
                '-preset', self.gpu_settings['preset'],
                '-b:v', self.bitrate
            ])
        else:
            # CPU编码设置
            cmd.extend([
                '-preset', self.gpu_settings['preset'],
                '-crf', str(self.gpu_settings['crf']),
                '-b:v', self.bitrate
            ])
        
        # 音频处理设置
        has_replace_audio = (self.audio_settings.get('replace_audio', False) and 
                           self.audio_settings.get('replace_audio_path', ''))
        has_background_audio = (self.audio_settings.get('background_audio', False) and 
                              self.audio_settings.get('background_audio_path', ''))
        
        if self.audio_settings['keep_original']:
            # 保留原视频音频
            cmd.extend(['-c:a', 'aac', '-b:a', '128k'])
            # 调整原音频音量
            if self.audio_settings['original_volume'] != 100:
                volume = self.audio_settings['original_volume'] / 100.0
                cmd.extend(['-af', f'volume={volume}'])
        elif has_replace_audio or has_background_audio:
            # 不保留原音频，但有替换音频或背景音频
            # FFmpegGPUProcessor目前不支持复杂音频处理，需要回退到VideoProcessor
            print(f"[FFmpegGPUProcessor] 检测到复杂音频处理需求，但GPU处理器尚不支持")
            print(f"[FFmpegGPUProcessor] 替换音频: {has_replace_audio}, 背景音频: {has_background_audio}")
            print(f"[FFmpegGPUProcessor] 建议使用VideoProcessor进行音频处理")
            cmd.extend(['-c:a', 'aac', '-b:a', '128k'])  # 临时保留音频编码设置
        else:
            # 不保留原音频，也没有其他音频源，移除音频轨道
            cmd.extend(['-an'])  # -an 表示不包含音频
            print(f"[FFmpegGPUProcessor] 没有音频源，移除音频轨道")
        
        # 分辨率和帧率
        cmd.extend(['-s', self.resolution, '-r', '30'])
        
        # 其他设置
        cmd.extend([
            '-movflags', '+faststart',  # 优化在线播放
            '-pix_fmt', 'yuv420p'       # 兼容性
        ])
        
        cmd.append(output_path)
        
        return cmd
    
    def _execute_ffmpeg_with_progress_pipe(self, cmd, total_duration, output_path, temp_files):
        """使用progress pipe执行FFmpeg命令并监控进度"""
        try:
            # 创建进程
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            
            # 添加到进程控制器
            self.process_controller.add_process(process, temp_files, output_path)
            
            # 连接进程控制器的进度信号到当前处理器
            self.process_controller.progress_updated.connect(
                lambda progress: self._on_video_progress(progress, self._current_video_index),
                Qt.QueuedConnection  # 使用队列连接确保线程安全
            )
            
            # 启动进度监控
            self.progress_monitor.monitor_progress_pipe(
                process, total_duration, 
                lambda progress: self._on_video_progress(progress, self._current_video_index)
            )
            
            # 等待完成
            stdout, stderr = process.communicate()
            
            # 断开信号连接
            try:
                self.process_controller.progress_updated.disconnect()
            except:
                pass  # 忽略断开连接的错误
            
            # 从进程控制器移除
            self.process_controller.remove_process(process)
            
            # 检查结果
            if process.returncode != 0 and not self.process_controller.is_cancelled():
                raise Exception(f"FFmpeg处理失败: {stderr}")
                
        except Exception as e:
            # 确保断开信号连接
            try:
                self.process_controller.progress_updated.disconnect()
            except:
                pass
            # 确保从进程控制器移除
            if 'process' in locals():
                self.process_controller.remove_process(process)
            if not self.process_controller.is_cancelled():
                raise e
    
    def _on_detailed_progress(self, progress):
        """处理详细进度更新"""
        self.detailed_progress_updated.emit(progress)
    
    def _on_process_error(self, error_msg):
        """处理进程错误"""
        if not self.process_controller.is_cancelled():
            self.process_finished.emit(f"进程错误: {error_msg}")
    
    def _on_video_progress(self, progress, video_index):
        """处理单个视频的进度更新"""
        try:
            # 计算总体进度：前面已完成的视频 + 当前视频的进度
            completed_videos = video_index - 1
            total_progress = (completed_videos + progress) / self.total_outputs
            
            # 确保进度在有效范围内
            total_progress = max(0.0, min(1.0, total_progress))
            
            # 发射详细进度信号
            self.detailed_progress_updated.emit(total_progress)
            
            # 发射整数进度信号（兼容现有UI）
            int_progress = int(total_progress * 100)
            self.progress_updated.emit(int_progress)
            
            # 调试输出
            print(f"视频 {video_index} 进度: {progress:.2f}, 总进度: {total_progress:.2f} ({int_progress}%)")
            
        except Exception as e:
            print(f"进度更新失败: {e}")
    

    
    def get_gpu_info(self):
        """获取GPU加速信息"""
        return {
            'gpu_detected': self.gpu_settings['use_gpu'],
            'hardware_encoder': self.gpu_settings['hardware_encoder'],
            'hardware_decoder': self.gpu_settings['hardware_decoder'],
            'preset': self.gpu_settings['preset']
        }
    
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
        
        # 取消所有活跃进程
        if hasattr(self, 'process_controller'):
            self.process_controller.cancel_all(timeout=2.0)
        
        # 等待线程结束
        self.wait()
