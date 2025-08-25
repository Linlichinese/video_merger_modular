"""
配置管理器模块

负责软件配置的加载、保存和管理功能
"""

import os
import json
from PyQt5.QtWidgets import QMessageBox


class ConfigManager:
    """配置管理器，负责处理软件配置的加载和保存"""
    
    def __init__(self, config_file='config.json'):
        """
        初始化配置管理器
        
        Args:
            config_file (str): 配置文件路径，默认为 'config.json'
        """
        # 使用稳定位置保存配置，避免因工作目录不同导致的丢失
        try:
            # 若未显式传入绝对路径，则落到用户目录下固定目录
            if not config_file or config_file == 'config.json' or not os.path.isabs(config_file):
                base_dir = os.path.join(os.path.expanduser('~'), '.video_merger')
                os.makedirs(base_dir, exist_ok=True)
                self.config_file = os.path.join(base_dir, 'config.json')
            else:
                self.config_file = os.path.abspath(config_file)
        except Exception:
            # 兜底：仍然使用相对路径，但后续保存会尽力创建目录
            self.config_file = config_file
        self.default_config = {
            'input_folder': '',
            'output_folder': '',
            'videos_per_output': 2,
            'total_outputs': 1,
            'keep_original': True,
            'original_volume': 100,
            'replace_audio': False,
            'replace_audio_path': '',
            'replace_audio_is_folder': False,
            'replace_volume': 100,
            'background_audio': False,
            'background_audio_path': '',
            'background_audio_is_folder': False,
            'background_volume': 50,
            'resolution': "1920x1080",
            'bitrate': "5000k",
            'reuse_material': True
        }
    
    def load_config(self):
        """
        加载配置文件
        
        Returns:
            dict: 配置字典，如果加载失败则返回默认配置
        """
        # 迁移策略：如果新位置不存在，但旧工作目录下存在 legacy 配置，则迁移
        if not os.path.exists(self.config_file):
            try:
                legacy_path = os.path.abspath('config.json')
                if os.path.exists(legacy_path) and os.path.abspath(legacy_path) != os.path.abspath(self.config_file):
                    with open(legacy_path, 'r', encoding='utf-8') as f:
                        legacy_cfg = json.load(f)
                    merged_legacy = self.default_config.copy()
                    merged_legacy.update(legacy_cfg)
                    # 将合并后的配置写入新位置
                    self.save_config(merged_legacy)
                    return merged_legacy
            except Exception:
                # 安静降级到默认流程
                pass
        
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                
                # 合并默认配置，确保所有必需的键都存在
                merged_config = self.default_config.copy()
                merged_config.update(config)
                return merged_config
                
            except Exception as e:
                self._show_error_message("加载配置错误", f"无法加载配置：{str(e)}")
                return self.default_config.copy()
        else:
            return self.default_config.copy()
    
    def save_config(self, config):
        """
        保存配置到文件
        
        Args:
            config (dict): 要保存的配置字典
        """
        try:
            # 确保配置文件目录存在
            config_dir = os.path.dirname(os.path.abspath(self.config_file)) or '.'
            os.makedirs(config_dir, exist_ok=True)
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
        except Exception as e:
            self._show_error_message("保存配置错误", f"无法保存配置：{str(e)}")
    
    def get_default_config(self):
        """
        获取默认配置
        
        Returns:
            dict: 默认配置字典的副本
        """
        return self.default_config.copy()
    
    def reset_config(self):
        """
        重置配置为默认值
        """
        try:
            if os.path.exists(self.config_file):
                os.remove(self.config_file)
        except Exception as e:
            self._show_error_message("重置配置错误", f"无法删除配置文件：{str(e)}")
    
    def validate_config(self, config):
        """
        验证配置的有效性
        
        Args:
            config (dict): 要验证的配置字典
            
        Returns:
            tuple: (是否有效, 错误信息列表)
        """
        errors = []
        
        # 检查必需的键
        for key in self.default_config:
            if key not in config:
                errors.append(f"缺少配置项: {key}")
        
        # 检查数值范围
        if config.get('videos_per_output', 0) < 1:
            errors.append("每个输出视频包含的视频数量必须大于0")
        
        if config.get('total_outputs', 0) < 1:
            errors.append("总输出视频数量必须大于0")
        
        if not (0 <= config.get('original_volume', 0) <= 200):
            errors.append("原音频音量必须在0-200之间")
        
        if not (0 <= config.get('replace_volume', 0) <= 200):
            errors.append("替换音频音量必须在0-200之间")
        
        if not (0 <= config.get('background_volume', 0) <= 200):
            errors.append("背景音音量必须在0-200之间")
        
        # 检查分辨率格式
        resolution = config.get('resolution', '')
        if resolution and 'x' not in resolution:
            errors.append("分辨率格式无效，应为 '宽x高' 格式")
        
        # 检查文件路径（如果启用了相应功能）
        if config.get('replace_audio', False):
            replace_path = config.get('replace_audio_path', '')
            replace_is_folder = config.get('replace_audio_is_folder', False)
            if replace_path:
                if replace_is_folder:
                    if not os.path.isdir(replace_path):
                        errors.append(f"替换音频文件夹不存在: {replace_path}")
                    else:
                        # 检查文件夹内是否有音频文件
                        audio_files = self._get_audio_files_from_folder(replace_path)
                        if not audio_files:
                            errors.append(f"替换音频文件夹中没有音频文件: {replace_path}")
                else:
                    if not os.path.isfile(replace_path):
                        errors.append(f"替换音频文件不存在: {replace_path}")
        
        if config.get('background_audio', False):
            background_path = config.get('background_audio_path', '')
            background_is_folder = config.get('background_audio_is_folder', False)
            if background_path:
                if background_is_folder:
                    if not os.path.isdir(background_path):
                        errors.append(f"背景音文件夹不存在: {background_path}")
                    else:
                        # 检查文件夹内是否有音频文件
                        audio_files = self._get_audio_files_from_folder(background_path)
                        if not audio_files:
                            errors.append(f"背景音文件夹中没有音频文件: {background_path}")
                else:
                    if not os.path.isfile(background_path):
                        errors.append(f"背景音文件不存在: {background_path}")
        
        return len(errors) == 0, errors
    
    def _show_error_message(self, title, message):
        """
        显示错误消息（如果在GUI环境中）
        
        Args:
            title (str): 错误标题
            message (str): 错误消息
        """
        try:
            # 尝试显示GUI消息框
            QMessageBox.warning(None, title, message)
        except:
            # 如果不在GUI环境中，则打印到控制台
            print(f"{title}: {message}")
    
    def export_config(self, export_path, config):
        """
        导出配置到指定路径
        
        Args:
            export_path (str): 导出路径
            config (dict): 要导出的配置
        """
        try:
            with open(export_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
        except Exception as e:
            self._show_error_message("导出配置错误", f"无法导出配置：{str(e)}")
    
    def import_config(self, import_path):
        """
        从指定路径导入配置
        
        Args:
            import_path (str): 导入路径
            
        Returns:
            dict or None: 导入的配置，失败时返回None
        """
        try:
            if not os.path.exists(import_path):
                self._show_error_message("导入配置错误", f"配置文件不存在: {import_path}")
                return None
            
            with open(import_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            # 验证导入的配置
            is_valid, errors = self.validate_config(config)
            if not is_valid:
                error_msg = "导入的配置文件无效:\n" + "\n".join(errors)
                self._show_error_message("配置验证错误", error_msg)
                return None
            
            return config
            
        except Exception as e:
            self._show_error_message("导入配置错误", f"无法导入配置：{str(e)}")
            return None
    
    def _get_audio_files_from_folder(self, folder_path):
        """
        从文件夹中获取音频文件列表
        
        Args:
            folder_path (str): 文件夹路径
            
        Returns:
            list: 音频文件路径列表
        """
        audio_extensions = ('.mp3', '.wav', '.ogg', '.flac', '.m4a', '.aac', '.wma')
        try:
            audio_files = []
            for file_name in os.listdir(folder_path):
                if file_name.lower().endswith(audio_extensions):
                    audio_files.append(os.path.join(folder_path, file_name))
            return audio_files
        except Exception:
            return []
