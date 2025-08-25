"""
GPU加速配置管理器

管理不同GPU厂商的硬件加速设置和优化参数
"""

import subprocess
import json
import os
from typing import Dict, Optional, List


class GPUConfigManager:
    """GPU配置管理器"""
    
    def __init__(self):
        self.gpu_info = self._detect_gpu_capabilities()
    
    def _detect_gpu_capabilities(self) -> Dict:
        """检测GPU硬件加速能力"""
        capabilities = {
            'vendor': 'unknown',
            'model': 'unknown',
            'hardware_encoder': 'libx264',  # 默认CPU编码
            'hardware_decoder': None,
            'preset': 'medium',
            'crf': 23,
            'use_gpu': False,
            'max_bitrate_multiplier': 2,
            'supports_b_frames': True,
            'supports_lookahead': False
        }
        
        # 检测NVIDIA GPU
        nvidia_info = self._detect_nvidia_gpu()
        if nvidia_info:
            capabilities.update(nvidia_info)
            return capabilities
        
        # 检测Intel GPU
        intel_info = self._detect_intel_gpu()
        if intel_info:
            capabilities.update(intel_info)
            return capabilities
        
        # 检测AMD GPU
        amd_info = self._detect_amd_gpu()
        if amd_info:
            capabilities.update(amd_info)
            return capabilities
        
        return capabilities
    
    def _detect_nvidia_gpu(self) -> Optional[Dict]:
        """检测NVIDIA GPU"""
        try:
            # 检查nvidia-smi
            result = subprocess.run(['nvidia-smi', '--query-gpu=name,memory.total', 
                                   '--format=csv,noheader,nounits'], 
                                  capture_output=True, text=True, timeout=5)
            
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                if lines:
                    gpu_name, memory = lines[0].split(', ')
                    
                    # 根据GPU型号选择最佳设置
                    preset = self._get_nvidia_preset(gpu_name)
                    
                    return {
                        'vendor': 'nvidia',
                        'model': gpu_name.strip(),
                        'memory_mb': int(memory),
                        'hardware_encoder': 'h264_nvenc',
                        'hardware_decoder': 'h264_cuvid',
                        'preset': preset,
                        'use_gpu': True,
                        'supports_lookahead': True,
                        'max_bitrate_multiplier': 3
                    }
        except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
            pass
        
        return None
    
    def _detect_intel_gpu(self) -> Optional[Dict]:
        """检测Intel GPU (QSV)"""
        try:
            # 检查ffmpeg是否支持QSV
            result = subprocess.run(['ffmpeg', '-hide_banner', '-encoders'], 
                                  capture_output=True, text=True, timeout=5)
            
            if 'h264_qsv' in result.stdout:
                return {
                    'vendor': 'intel',
                    'model': 'Intel Graphics (QSV)',
                    'hardware_encoder': 'h264_qsv',
                    'hardware_decoder': 'h264_qsv',
                    'preset': 'medium',
                    'use_gpu': True,
                    'supports_lookahead': True,
                    'max_bitrate_multiplier': 2
                }
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        
        return None
    
    def _detect_amd_gpu(self) -> Optional[Dict]:
        """检测AMD GPU (AMF)"""
        try:
            # 检查ffmpeg是否支持AMF
            result = subprocess.run(['ffmpeg', '-hide_banner', '-encoders'], 
                                  capture_output=True, text=True, timeout=5)
            
            if 'h264_amf' in result.stdout:
                return {
                    'vendor': 'amd',
                    'model': 'AMD Graphics (AMF)',
                    'hardware_encoder': 'h264_amf',
                    'hardware_decoder': None,
                    'preset': 'balanced',
                    'use_gpu': True,
                    'supports_lookahead': False,
                    'max_bitrate_multiplier': 2
                }
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        
        return None
    
    def _get_nvidia_preset(self, gpu_name: str) -> str:
        """根据NVIDIA GPU型号选择最佳preset"""
        gpu_name = gpu_name.lower()
        
        # 高端GPU使用更快的preset
        if any(x in gpu_name for x in ['rtx 40', 'rtx 30', 'rtx 20', 'gtx 16']):
            return 'p2'  # 快速preset
        elif any(x in gpu_name for x in ['rtx 10', 'gtx 10']):
            return 'p4'  # 平衡preset
        else:
            return 'p6'  # 质量优先preset
    
    def get_ffmpeg_params(self, bitrate: str, resolution: str, quality: str = 'high') -> Dict:
        """获取FFmpeg参数"""
        params = {
            'input_params': [],
            'video_params': [],
            'audio_params': ['-c:a', 'aac', '-b:a', '128k'],
            'output_params': ['-movflags', '+faststart', '-pix_fmt', 'yuv420p']
        }
        
        # 硬件解码
        if self.gpu_info['hardware_decoder']:
            if self.gpu_info['vendor'] == 'nvidia':
                params['input_params'].extend(['-hwaccel', 'cuda'])
            elif self.gpu_info['vendor'] == 'intel':
                params['input_params'].extend(['-hwaccel', 'qsv'])
        
        # 视频编码参数
        encoder = self.gpu_info['hardware_encoder']
        params['video_params'].extend(['-c:v', encoder])
        
        # 编码器特定参数
        if encoder == 'h264_nvenc':
            params['video_params'].extend(self._get_nvenc_params(bitrate, quality))
        elif encoder == 'h264_qsv':
            params['video_params'].extend(self._get_qsv_params(bitrate, quality))
        elif encoder == 'h264_amf':
            params['video_params'].extend(self._get_amf_params(bitrate, quality))
        else:
            # CPU编码
            params['video_params'].extend(self._get_cpu_params(bitrate, quality))
        
        # 分辨率和帧率
        params['video_params'].extend(['-s', resolution, '-r', '30'])
        
        return params
    
    def _get_nvenc_params(self, bitrate: str, quality: str) -> List[str]:
        """获取NVIDIA NVENC参数"""
        params = [
            '-preset', self.gpu_info['preset'],
            '-rc', 'vbr',
            '-b:v', bitrate
        ]
        
        # 质量设置
        if quality == 'high':
            params.extend(['-cq', '20', '-qmin', '18', '-qmax', '24'])
        elif quality == 'medium':
            params.extend(['-cq', '23', '-qmin', '20', '-qmax', '26'])
        else:  # low
            params.extend(['-cq', '26', '-qmin', '22', '-qmax', '28'])
        
        # 高级设置
        if self.gpu_info.get('supports_lookahead'):
            params.extend(['-rc-lookahead', '20'])
        
        # 比特率控制
        bitrate_num = int(bitrate.rstrip('k'))
        max_bitrate = bitrate_num * self.gpu_info['max_bitrate_multiplier']
        params.extend([
            '-maxrate', f'{max_bitrate}k',
            '-bufsize', f'{max_bitrate}k'
        ])
        
        return params
    
    def _get_qsv_params(self, bitrate: str, quality: str) -> List[str]:
        """获取Intel QSV参数"""
        params = [
            '-preset', self.gpu_info['preset'],
            '-b:v', bitrate
        ]
        
        # 质量设置
        if quality == 'high':
            params.extend(['-global_quality', '20'])
        elif quality == 'medium':
            params.extend(['-global_quality', '23'])
        else:  # low
            params.extend(['-global_quality', '26'])
        
        return params
    
    def _get_amf_params(self, bitrate: str, quality: str) -> List[str]:
        """获取AMD AMF参数"""
        params = [
            '-usage', 'transcoding',
            '-b:v', bitrate
        ]
        
        # 质量设置
        if quality == 'high':
            params.extend(['-qp_i', '20', '-qp_p', '22'])
        elif quality == 'medium':
            params.extend(['-qp_i', '23', '-qp_p', '25'])
        else:  # low
            params.extend(['-qp_i', '26', '-qp_p', '28'])
        
        return params
    
    def _get_cpu_params(self, bitrate: str, quality: str) -> List[str]:
        """获取CPU编码参数"""
        params = [
            '-preset', self.gpu_info['preset'],
            '-b:v', bitrate
        ]
        
        # 质量设置
        if quality == 'high':
            params.extend(['-crf', '20'])
        elif quality == 'medium':
            params.extend(['-crf', '23'])
        else:  # low
            params.extend(['-crf', '26'])
        
        return params
    
    def get_performance_estimate(self, input_duration: float, resolution: str) -> Dict:
        """估算处理性能"""
        # 基础性能倍数
        base_multiplier = 1.0
        
        if self.gpu_info['use_gpu']:
            if self.gpu_info['vendor'] == 'nvidia':
                base_multiplier = 3.0  # NVENC通常快3倍
            elif self.gpu_info['vendor'] == 'intel':
                base_multiplier = 2.0  # QSV通常快2倍
            elif self.gpu_info['vendor'] == 'amd':
                base_multiplier = 2.5  # AMF通常快2.5倍
        
        # 分辨率影响
        width, height = map(int, resolution.split('x'))
        pixel_count = width * height
        
        if pixel_count <= 1920 * 1080:  # 1080p及以下
            resolution_multiplier = 1.0
        elif pixel_count <= 2560 * 1440:  # 1440p
            resolution_multiplier = 0.7
        else:  # 4K及以上
            resolution_multiplier = 0.4
        
        estimated_speed = base_multiplier * resolution_multiplier
        estimated_time = input_duration / estimated_speed
        
        return {
            'estimated_speed_multiplier': estimated_speed,
            'estimated_processing_time': estimated_time,
            'gpu_acceleration': self.gpu_info['use_gpu'],
            'encoder': self.gpu_info['hardware_encoder']
        }
    
    def get_gpu_status(self) -> Dict:
        """获取GPU状态信息"""
        return {
            'gpu_detected': self.gpu_info['use_gpu'],
            'vendor': self.gpu_info['vendor'],
            'model': self.gpu_info['model'],
            'hardware_encoder': self.gpu_info['hardware_encoder'],
            'hardware_decoder': self.gpu_info['hardware_decoder'],
            'preset': self.gpu_info['preset'],
            'supports_lookahead': self.gpu_info.get('supports_lookahead', False)
        }
