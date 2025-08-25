"""
主窗口模块

视频合成软件的主用户界面窗口
"""

import os
import time
from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                            QLabel, QLineEdit, QPushButton, QComboBox, QSpinBox, 
                            QCheckBox, QFileDialog, QProgressBar, QMessageBox, QGroupBox,
                            QSlider, QTabWidget, QDoubleSpinBox, QButtonGroup, QRadioButton)
from PyQt5.QtCore import Qt, QTimer
from core import VideoProcessor
from core.ffmpeg_processor import FFmpegGPUProcessor
from core.gpu_config import GPUConfigManager
from core.video_splitter import VideoSplitter
from core.batch_processor import BatchProcessor, BatchJobType
from config import ConfigManager
from .batch_widgets import MultiFolderManager, BatchMode, FolderStatus


class VideoMergerApp(QMainWindow):
    """视频合成软件主窗口"""
    
    def __init__(self):
        super().__init__()
        self.config_manager = ConfigManager()
        self.gpu_config_manager = GPUConfigManager()
        self.processor = None
        self.splitter = None  # 视频分割器
        
        # 批处理相关
        self.batch_processor = BatchProcessor(max_concurrent_jobs=2, parent=self)
        self.batch_processor.set_gpu_config_manager(self.gpu_config_manager)
        self.batch_mode = BatchMode.SINGLE_FOLDER  # 默认单文件夹模式
        self.multi_folder_manager = None
        
        # 防重复完成通知 - 分别处理合成和分割
        self._merge_completion_notified = False
        self._split_completion_notified = False
        
        # 取消按钮防抖相关
        self._cancel_requested = False
        self._last_cancel_time = 0
        self._cancel_debounce_ms = 500  # 500ms防抖间隔
        
        # 平滑进度更新相关
        self._current_progress = 0.0
        self._target_progress = 0.0
        self._progress_timer = QTimer()
        self._progress_timer.timeout.connect(self._update_smooth_progress)
        self._progress_update_interval = 50  # 50ms更新一次
        
        self.init_ui()
        self.load_config()
        self._setup_batch_signals()
        
    def init_ui(self):
        """初始化用户界面"""
        self.setWindowTitle("视频批量处理工具")
        self.setGeometry(100, 100, 800, 750)
        self.setMinimumSize(750, 700)
        
        # 主部件和布局
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(15, 15, 15, 15)
        
        # 创建标签页
        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget)
        
        # 创建简化的合成标签页
        from .simple_merge_tab import SimpleMergeTab
        self.simple_merge_tab = SimpleMergeTab()
        self.tab_widget.addTab(self.simple_merge_tab, "📹 视频合成")
        self._setup_simple_merge_signals()
        
        # 创建简化的分割标签页
        from .simple_split_tab import SimpleSplitTab
        self.simple_split_tab = SimpleSplitTab()
        self.tab_widget.addTab(self.simple_split_tab, "✂️ 视频分割")
        self._setup_simple_split_signals()
        
        # 创建自动模式标签页
        from .auto_mode_tab import AutoModeTab
        self.auto_mode_tab = AutoModeTab(self.batch_processor)
        self.tab_widget.addTab(self.auto_mode_tab, "🔄 自动模式")
        self._setup_auto_mode_signals()
        
        # 创建隐藏的进度条和按钮（兼容性，但不显示）
        self._create_progress_bar(main_layout)
        self._create_buttons(main_layout)
        
        # 隐藏底部控件，因为简化标签页已包含完整的控制面板
        # 包括进度条，避免重复显示
        self.start_btn.hide()
        self.cancel_btn.hide()
        self.reset_dedup_btn.hide()
        self.progress_bar.hide()
        self.progress_label.hide()
    
    def _init_merge_tab(self):
        """初始化视频合成标签页"""
        merge_layout = QVBoxLayout(self.merge_tab)
        merge_layout.setSpacing(15)
        merge_layout.setContentsMargins(20, 20, 20, 20)
        
        # 添加各个UI组件
        self._create_folder_settings(merge_layout)
        self._create_merge_settings(merge_layout)
        self._create_audio_settings(merge_layout)
        self._create_output_settings(merge_layout)
    
    def _init_split_tab(self):
        """初始化视频分割标签页"""
        split_layout = QVBoxLayout(self.split_tab)
        split_layout.setSpacing(15)
        split_layout.setContentsMargins(20, 20, 20, 20)
        
        # 创建分割相关UI组件
        self._create_split_input_settings(split_layout)
        self._create_split_duration_settings(split_layout)
        self._create_split_output_settings(split_layout)
        
    def _create_folder_settings(self, main_layout):
        """创建文件夹设置区域"""
        folder_group = QGroupBox("文件夹设置")
        folder_layout = QVBoxLayout()
        
        # 处理模式选择
        mode_layout = QHBoxLayout()
        mode_layout.addWidget(QLabel("处理模式:"))
        
        self.mode_button_group = QButtonGroup()
        self.single_mode_radio = QRadioButton("单文件夹模式")
        self.multi_mode_radio = QRadioButton("多文件夹批处理模式")
        self.single_mode_radio.setChecked(True)  # 默认选中单文件夹模式
        
        self.mode_button_group.addButton(self.single_mode_radio, 0)
        self.mode_button_group.addButton(self.multi_mode_radio, 1)
        self.mode_button_group.buttonClicked.connect(self._on_mode_changed)
        
        mode_layout.addWidget(self.single_mode_radio)
        mode_layout.addWidget(self.multi_mode_radio)
        mode_layout.addStretch()
        folder_layout.addLayout(mode_layout)
        
        # 单文件夹模式区域
        self.single_folder_widget = QWidget()
        single_folder_layout = QVBoxLayout(self.single_folder_widget)
        single_folder_layout.setContentsMargins(0, 0, 0, 0)
        
        # 输入文件夹选择
        input_layout = QHBoxLayout()
        input_layout.addWidget(QLabel("输入文件夹:"))
        self.input_folder_edit = QLineEdit()
        self.input_folder_edit.setReadOnly(True)
        input_layout.addWidget(self.input_folder_edit, 1)
        self.input_browse_btn = QPushButton("浏览...")
        self.input_browse_btn.clicked.connect(self.browse_input)
        input_layout.addWidget(self.input_browse_btn)
        single_folder_layout.addLayout(input_layout)
        
        # 输出文件夹选择
        output_layout = QHBoxLayout()
        output_layout.addWidget(QLabel("输出文件夹:"))
        self.output_folder_edit = QLineEdit()
        self.output_folder_edit.setReadOnly(True)
        output_layout.addWidget(self.output_folder_edit, 1)
        self.output_browse_btn = QPushButton("浏览...")
        self.output_browse_btn.clicked.connect(self.browse_output)
        output_layout.addWidget(self.output_browse_btn)
        single_folder_layout.addLayout(output_layout)
        
        folder_layout.addWidget(self.single_folder_widget)
        
        # 多文件夹模式区域
        self.multi_folder_widget = QWidget()
        multi_folder_layout = QVBoxLayout(self.multi_folder_widget)
        multi_folder_layout.setContentsMargins(0, 0, 0, 0)
        
        # 统一输出文件夹选择
        multi_output_layout = QHBoxLayout()
        multi_output_layout.addWidget(QLabel("统一输出文件夹:"))
        self.multi_output_folder_edit = QLineEdit()
        self.multi_output_folder_edit.setReadOnly(True)
        multi_output_layout.addWidget(self.multi_output_folder_edit, 1)
        self.multi_output_browse_btn = QPushButton("浏览...")
        self.multi_output_browse_btn.clicked.connect(self.browse_multi_output)
        multi_output_layout.addWidget(self.multi_output_browse_btn)
        multi_folder_layout.addLayout(multi_output_layout)
        
        # 多文件夹管理器
        self.multi_folder_manager = MultiFolderManager()
        self.multi_folder_manager.folders_changed.connect(self._on_multi_folders_changed)
        multi_folder_layout.addWidget(self.multi_folder_manager)
        
        folder_layout.addWidget(self.multi_folder_widget)
        
        # 默认隐藏多文件夹模式
        self.multi_folder_widget.setVisible(False)
        
        folder_group.setLayout(folder_layout)
        main_layout.addWidget(folder_group)
        
    def _create_merge_settings(self, main_layout):
        """创建合成设置区域"""
        merge_group = QGroupBox("合成设置")
        merge_layout = QVBoxLayout()
        
        # 每个输出视频包含的视频数量
        videos_per_output_layout = QHBoxLayout()
        videos_per_output_layout.addWidget(QLabel("每个输出视频包含的视频数量:"))
        self.videos_per_output_spin = QSpinBox()
        self.videos_per_output_spin.setMinimum(1)
        self.videos_per_output_spin.setValue(2)
        self.videos_per_output_spin.setMaximum(100)
        videos_per_output_layout.addWidget(self.videos_per_output_spin)
        merge_layout.addLayout(videos_per_output_layout)
        
        # 总输出视频数量
        total_outputs_layout = QHBoxLayout()
        total_outputs_layout.addWidget(QLabel("总输出视频数量:"))
        self.total_outputs_spin = QSpinBox()
        self.total_outputs_spin.setMinimum(1)
        self.total_outputs_spin.setValue(1)
        self.total_outputs_spin.setMaximum(100000)
        total_outputs_layout.addWidget(self.total_outputs_spin)
        merge_layout.addLayout(total_outputs_layout)
        
        merge_group.setLayout(merge_layout)
        main_layout.addWidget(merge_group)
        
    def _create_audio_settings(self, main_layout):
        """创建音频设置区域"""
        audio_group = QGroupBox("音频设置（替换音频和背景音会自动循环播放）")
        audio_layout = QVBoxLayout()
        
        # 保留原音频设置
        self._create_original_audio_settings(audio_layout)
        
        # 替换音频设置
        self._create_replace_audio_settings(audio_layout)
        
        # 背景音设置
        self._create_background_audio_settings(audio_layout)
        
        audio_group.setLayout(audio_layout)
        main_layout.addWidget(audio_group)
        
    def _create_original_audio_settings(self, audio_layout):
        """创建原音频设置"""
        original_audio_layout = QHBoxLayout()
        self.keep_original_check = QCheckBox("保留原视频音频")
        self.keep_original_check.setChecked(True)
        original_audio_layout.addWidget(self.keep_original_check)
        
        # 原音频音量
        original_audio_layout.addWidget(QLabel("音量:"))
        self.original_volume_slider = QSlider(Qt.Horizontal)
        self.original_volume_slider.setRange(0, 200)
        self.original_volume_slider.setValue(100)
        self.original_volume_slider.setMinimumWidth(150)
        original_audio_layout.addWidget(self.original_volume_slider)
        
        self.original_volume_label = QLabel("100%")
        original_audio_layout.addWidget(self.original_volume_label)
        self.original_volume_slider.valueChanged.connect(
            lambda value: self.original_volume_label.setText(f"{value}%")
        )
        audio_layout.addLayout(original_audio_layout)
        
    def _create_replace_audio_settings(self, audio_layout):
        """创建替换音频设置"""
        replace_audio_layout = QHBoxLayout()
        self.replace_audio_check = QCheckBox("替换视频音频")
        self.replace_audio_check.setChecked(False)
        replace_audio_layout.addWidget(self.replace_audio_check)
        
        # 添加选择类型的下拉框
        self.replace_audio_type_combo = QComboBox()
        self.replace_audio_type_combo.addItems(["选择文件", "选择文件夹"])
        self.replace_audio_type_combo.setEnabled(False)
        self.replace_audio_type_combo.currentTextChanged.connect(self.on_replace_audio_type_changed)
        replace_audio_layout.addWidget(self.replace_audio_type_combo)
        
        self.replace_audio_edit = QLineEdit()
        self.replace_audio_edit.setReadOnly(True)
        self.replace_audio_edit.setEnabled(False)
        replace_audio_layout.addWidget(self.replace_audio_edit, 1)
        
        self.replace_audio_btn = QPushButton("浏览...")
        self.replace_audio_btn.setEnabled(False)
        self.replace_audio_btn.clicked.connect(self.browse_replace_audio)
        replace_audio_layout.addWidget(self.replace_audio_btn)
        
        # 替换音频音量
        replace_audio_layout.addWidget(QLabel("音量:"))
        self.replace_volume_slider = QSlider(Qt.Horizontal)
        self.replace_volume_slider.setRange(0, 200)
        self.replace_volume_slider.setValue(100)
        self.replace_volume_slider.setMinimumWidth(100)
        self.replace_volume_slider.setEnabled(False)
        replace_audio_layout.addWidget(self.replace_volume_slider)
        
        self.replace_volume_label = QLabel("100%")
        self.replace_volume_label.setEnabled(False)
        replace_audio_layout.addWidget(self.replace_volume_label)
        self.replace_volume_slider.valueChanged.connect(
            lambda value: self.replace_volume_label.setText(f"{value}%")
        )
        
        # 连接复选框状态变化
        self.replace_audio_check.stateChanged.connect(self.toggle_replace_audio)
        audio_layout.addLayout(replace_audio_layout)
        
    def _create_background_audio_settings(self, audio_layout):
        """创建背景音设置"""
        background_audio_layout = QHBoxLayout()
        self.background_audio_check = QCheckBox("添加背景音")
        self.background_audio_check.setChecked(False)
        background_audio_layout.addWidget(self.background_audio_check)
        
        # 添加选择类型的下拉框
        self.background_audio_type_combo = QComboBox()
        self.background_audio_type_combo.addItems(["选择文件", "选择文件夹"])
        self.background_audio_type_combo.setEnabled(False)
        self.background_audio_type_combo.currentTextChanged.connect(self.on_background_audio_type_changed)
        background_audio_layout.addWidget(self.background_audio_type_combo)
        
        self.background_audio_edit = QLineEdit()
        self.background_audio_edit.setReadOnly(True)
        self.background_audio_edit.setEnabled(False)
        background_audio_layout.addWidget(self.background_audio_edit, 1)
        
        self.background_audio_btn = QPushButton("浏览...")
        self.background_audio_btn.setEnabled(False)
        self.background_audio_btn.clicked.connect(self.browse_background_audio)
        background_audio_layout.addWidget(self.background_audio_btn)
        
        # 背景音音量
        background_audio_layout.addWidget(QLabel("音量:"))
        self.background_volume_slider = QSlider(Qt.Horizontal)
        self.background_volume_slider.setRange(0, 200)
        self.background_volume_slider.setValue(50)  # 背景音默认音量较低
        self.background_volume_slider.setMinimumWidth(100)
        self.background_volume_slider.setEnabled(False)
        background_audio_layout.addWidget(self.background_volume_slider)
        
        self.background_volume_label = QLabel("50%")
        self.background_volume_label.setEnabled(False)
        background_audio_layout.addWidget(self.background_volume_label)
        self.background_volume_slider.valueChanged.connect(
            lambda value: self.background_volume_label.setText(f"{value}%")
        )
        
        # 连接复选框状态变化
        self.background_audio_check.stateChanged.connect(self.toggle_background_audio)
        audio_layout.addLayout(background_audio_layout)
        
    def _create_output_settings(self, main_layout):
        """创建输出设置区域"""
        output_group = QGroupBox("输出设置")
        output_layout = QVBoxLayout()
        
        # 分辨率设置
        resolution_layout = QHBoxLayout()
        resolution_layout.addWidget(QLabel("输出分辨率:"))
        self.resolution_combo = QComboBox()
        self.resolution_combo.addItems(["1920x1080", "1080x1920", "1280x720", "2560x1440", "3840x2160"])
        output_layout.addLayout(resolution_layout)
        resolution_layout.addWidget(self.resolution_combo)
        
        # 码率设置
        bitrate_layout = QHBoxLayout()
        bitrate_layout.addWidget(QLabel("输出码率 (例如 5000k):"))
        self.bitrate_edit = QLineEdit("5000k")
        bitrate_layout.addWidget(self.bitrate_edit)
        output_layout.addLayout(bitrate_layout)
        
        # GPU加速设置
        gpu_layout = QVBoxLayout()
        self.use_gpu_checkbox = QCheckBox("启用GPU硬件加速")
        self.use_gpu_checkbox.setChecked(self.gpu_config_manager.gpu_info['use_gpu'])
        self.use_gpu_checkbox.toggled.connect(self._on_gpu_setting_changed)
        gpu_layout.addWidget(self.use_gpu_checkbox)
        
        # GPU状态显示
        self.gpu_status_label = QLabel("")
        self.gpu_status_label.setStyleSheet("color: #666; font-size: 11px;")
        gpu_layout.addWidget(self.gpu_status_label)
        
        # 质量设置
        quality_layout = QHBoxLayout()
        quality_layout.addWidget(QLabel("编码质量:"))
        self.quality_combo = QComboBox()
        self.quality_combo.addItems(["高质量", "中等质量", "快速编码"])
        self.quality_combo.setCurrentText("高质量")
        quality_layout.addWidget(self.quality_combo)
        gpu_layout.addLayout(quality_layout)
        
        output_layout.addLayout(gpu_layout)
        
        # 素材重用设置
        reuse_layout = QHBoxLayout()
        self.reuse_checkbox = QCheckBox("允许素材重复使用")
        self.reuse_checkbox.setChecked(True)
        reuse_layout.addWidget(self.reuse_checkbox)
        output_layout.addLayout(reuse_layout)
        
        output_group.setLayout(output_layout)
        main_layout.addWidget(output_group)
        
    def _create_progress_bar(self, main_layout):
        """创建进度条"""
        progress_layout = QVBoxLayout()
        
        # 主进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        progress_layout.addWidget(self.progress_bar)
        
        # 进度标签
        self.progress_label = QLabel("准备就绪")
        self.progress_label.setAlignment(Qt.AlignCenter)
        self.progress_label.setStyleSheet("color: #666; font-size: 11px;")
        progress_layout.addWidget(self.progress_label)
        
        main_layout.addLayout(progress_layout)
        
    def _create_buttons(self, main_layout):
        """创建按钮"""
        btn_layout = QHBoxLayout()
        
        self.start_btn = QPushButton("开始处理")
        self.start_btn.clicked.connect(self.start_processing)
        self.start_btn.setMinimumHeight(30)
        btn_layout.addWidget(self.start_btn)
        
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.clicked.connect(self.cancel_processing)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setMinimumHeight(30)
        btn_layout.addWidget(self.cancel_btn)
        
        # 添加清空去重状态按钮
        self.reset_dedup_btn = QPushButton("清空去重记录")
        self.reset_dedup_btn.clicked.connect(self.reset_dedup_state)
        self.reset_dedup_btn.setMinimumHeight(30)
        self.reset_dedup_btn.setToolTip("清空已记录的去重状态，重新开始去重逻辑")
        btn_layout.addWidget(self.reset_dedup_btn)
        
        # 添加管理去重状态按钮
        self.manage_dedup_btn = QPushButton("管理去重记录")
        self.manage_dedup_btn.clicked.connect(self.manage_dedup_states)
        self.manage_dedup_btn.setMinimumHeight(30)
        self.manage_dedup_btn.setToolTip("查看和管理所有去重状态文件")
        btn_layout.addWidget(self.manage_dedup_btn)
        
        main_layout.addLayout(btn_layout)
    
    def toggle_replace_audio(self, state):
        """切换替换音频相关控件的启用状态"""
        enabled = state == Qt.Checked
        self.replace_audio_type_combo.setEnabled(enabled)
        self.replace_audio_edit.setEnabled(enabled)
        self.replace_audio_btn.setEnabled(enabled)
        self.replace_volume_slider.setEnabled(enabled)
        self.replace_volume_label.setEnabled(enabled)
    
    def toggle_background_audio(self, state):
        """切换背景音相关控件的启用状态"""
        enabled = state == Qt.Checked
        self.background_audio_type_combo.setEnabled(enabled)
        self.background_audio_edit.setEnabled(enabled)
        self.background_audio_btn.setEnabled(enabled)
        self.background_volume_slider.setEnabled(enabled)
        self.background_volume_label.setEnabled(enabled)
    
    def on_replace_audio_type_changed(self):
        """替换音频类型改变时清空路径"""
        self.replace_audio_edit.setText("")
    
    def on_background_audio_type_changed(self):
        """背景音类型改变时清空路径"""
        self.background_audio_edit.setText("")
    
    def browse_input(self):
        """浏览选择输入文件夹"""
        folder = QFileDialog.getExistingDirectory(self, "选择输入文件夹")
        if folder:
            self.input_folder_edit.setText(folder)
    
    def browse_output(self):
        """浏览选择输出文件夹"""
        folder = QFileDialog.getExistingDirectory(self, "选择输出文件夹")
        if folder:
            self.output_folder_edit.setText(folder)
    
    def browse_replace_audio(self):
        """浏览选择替换音频文件或文件夹"""
        if self.replace_audio_type_combo.currentText() == "选择文件":
            file, _ = QFileDialog.getOpenFileName(
                self, "选择替换音频文件", "", 
                "音频文件 (*.mp3 *.wav *.ogg *.flac *.m4a)"
            )
            if file:
                self.replace_audio_edit.setText(file)
        else:  # 选择文件夹
            folder = QFileDialog.getExistingDirectory(self, "选择替换音频文件夹")
            if folder:
                self.replace_audio_edit.setText(folder)
    
    def browse_background_audio(self):
        """浏览选择背景音文件或文件夹"""
        if self.background_audio_type_combo.currentText() == "选择文件":
            file, _ = QFileDialog.getOpenFileName(
                self, "选择背景音文件", "", 
                "音频文件 (*.mp3 *.wav *.ogg *.flac *.m4a)"
            )
            if file:
                self.background_audio_edit.setText(file)
        else:  # 选择文件夹
            folder = QFileDialog.getExistingDirectory(self, "选择背景音文件夹")
            if folder:
                self.background_audio_edit.setText(folder)
    
    def start_processing(self):
        """开始视频处理（合成或分割）"""
        # 根据当前标签页决定处理模式
        current_tab_index = self.tab_widget.currentIndex()
        
        if current_tab_index == 0:  # 合成标签页
            self.start_merge_processing()
        elif current_tab_index == 1:  # 分割标签页
            self.start_split_processing()
        elif current_tab_index == 2:  # 自动模式标签页
            # 自动模式有自己的启动逻辑，在其内部处理
            pass
    
    def start_merge_processing(self):
        """开始视频合成处理"""
        # 使用简化标签页进行批量处理
        self._start_multi_folder_merge()
    
    def _start_single_folder_merge(self):
        """开始单文件夹合成处理"""
        # 验证输入
        input_folder = self.input_folder_edit.text()
        output_folder = self.output_folder_edit.text()
        
        if not input_folder or not os.path.isdir(input_folder):
            QMessageBox.warning(self, "输入错误", "请选择有效的输入文件夹")
            return
        
        if not output_folder or not os.path.isdir(output_folder):
            QMessageBox.warning(self, "输出错误", "请选择有效的输出文件夹")
            return
        
        # 获取音频设置
        audio_settings = self._get_audio_settings()
        
        # 验证音频设置
        if not self._validate_audio_settings(audio_settings):
            return
        
        videos_per_output = self.videos_per_output_spin.value()
        total_outputs = self.total_outputs_spin.value()
        resolution = self.resolution_combo.currentText()
        bitrate = self.bitrate_edit.text()
        reuse_material = self.reuse_checkbox.isChecked()
        
        if not bitrate:
            QMessageBox.warning(self, "输入错误", "请设置输出码率")
            return
        
        # 检查视频文件
        if not self._check_video_files(input_folder, videos_per_output, total_outputs, reuse_material):
            return
        
        # 开始处理
        self._start_video_processing(
            input_folder, output_folder, videos_per_output, total_outputs,
            resolution, bitrate, reuse_material, audio_settings
        )
    
    def _start_multi_folder_merge(self):
        """开始多文件夹批处理合成"""
        # 从简化合成标签页获取设置
        if not hasattr(self, 'simple_merge_tab'):
            QMessageBox.warning(self, "系统错误", "合成标签页未初始化")
            return
        
        # 验证统一输出文件夹
        output_folder = self.simple_merge_tab.output_folder_edit.text()
        if not output_folder or not os.path.isdir(output_folder):
            QMessageBox.warning(self, "输出错误", "请选择有效的统一输出文件夹")
            return
        
        # 检查是否有待处理的文件夹
        selected_folders = [folder for folder in self.simple_merge_tab.folder_list if folder.selected]
        if not selected_folders:
            QMessageBox.warning(self, "输入错误", "请先添加并选择要处理的文件夹")
            return
        
        # 获取处理设置（简化版本无复杂音频设置）
        audio_settings = {
            'keep_original': True,
            'original_volume': 100,
            'replace_audio': False,
            'replace_audio_path': '',
            'replace_audio_is_folder': False,
            'replace_volume': 100,
            'background_audio': False,
            'background_audio_path': '',
            'background_audio_is_folder': False,
            'background_volume': 50
        }
        
        videos_per_output = self.simple_merge_tab.videos_per_output_spin.value()
        total_outputs = self.simple_merge_tab.total_outputs_spin.value()
        resolution = self.simple_merge_tab.resolution_combo.currentText()
        bitrate = self.simple_merge_tab.bitrate_edit.text()
        reuse_material = self.simple_merge_tab.reuse_material_check.isChecked()
        use_gpu = self.simple_merge_tab.use_gpu_check.isChecked()
        
        if not bitrate:
            QMessageBox.warning(self, "输入错误", "请设置输出码率")
            return
        
        # 获取质量设置
        quality_map = {"高质量": "high", "中等质量": "medium", "快速编码": "low"}
        quality = quality_map.get(self.simple_merge_tab.quality_combo.currentText(), "high")
        
        # 为每个选中文件夹创建批处理任务
        success_count = 0
        for folder_info in selected_folders:
            # 为每个文件夹创建独立的输出子文件夹，保持原文件夹名称
            folder_name = os.path.basename(folder_info.path)
            folder_output = os.path.join(output_folder, folder_name)
            os.makedirs(folder_output, exist_ok=True)
            
            success = self.batch_processor.add_merge_job(
                folder_info.path,
                folder_output,
                videos_per_output,
                total_outputs,
                resolution,
                bitrate,
                reuse_material,
                audio_settings,
                use_gpu,
                quality
            )
            
            if success:
                success_count += 1
            else:
                QMessageBox.warning(
                    self, "添加任务失败", 
                    f"无法添加文件夹 '{folder_name}' 到批处理队列"
                )
        
        if success_count == 0:
            QMessageBox.warning(self, "批处理失败", "没有成功添加任何处理任务")
            return
        
        # 开始批处理
        if self.batch_processor.start_batch():
            QMessageBox.information(
                self, "批处理开始", 
                f"成功启动批处理，共 {success_count} 个文件夹待处理"
            )
        else:
            QMessageBox.warning(self, "启动失败", "无法启动批处理")
    
    def start_split_processing(self):
        """开始视频分割处理"""
        # 从简化分割标签页获取设置
        if not hasattr(self, 'simple_split_tab'):
            QMessageBox.warning(self, "系统错误", "分割标签页未初始化")
            return
        
        # 检查是否有选中的文件夹
        selected_folders = [folder for folder in self.simple_split_tab.folder_list if folder.selected]
        if not selected_folders:
            QMessageBox.warning(self, "输入错误", "请先添加并选择要处理的文件夹")
            return
        
        # 检查输出文件夹
        output_folder = self.simple_split_tab.output_folder_edit.text()
        if not output_folder:
            QMessageBox.warning(self, "输出错误", "请选择输出文件夹")
            return
        
        # 验证时长设置
        min_duration = self.simple_split_tab.min_duration_spin.value()
        max_duration = self.simple_split_tab.max_duration_spin.value()
        
        if min_duration >= max_duration:
            QMessageBox.warning(self, "时长设置错误", "最小时长必须小于最大时长")
            return
        
        # 获取输出设置
        resolution_text = self.simple_split_tab.resolution_combo.currentText()
        resolution = None if resolution_text == "保持原分辨率" else resolution_text
        
        bitrate = self.simple_split_tab.bitrate_edit.text()
        if not bitrate:
            QMessageBox.warning(self, "码率设置错误", "请设置输出码率")
            return
        
        quality_map = {"高质量": "high", "中等质量": "medium", "快速编码": "low"}
        quality = quality_map.get(self.simple_split_tab.quality_combo.currentText(), "medium")
        save_metadata = self.simple_split_tab.save_metadata_check.isChecked()
        delete_original = self.simple_split_tab.delete_original_check.isChecked()
        
        # 如果选择删除原视频，进行额外确认
        if delete_original:
            reply = QMessageBox.question(
                self,
                "确认删除原视频",
                "您选择了在分割完成后删除原视频文件。\n\n"
                "⚠️ 警告：此操作不可撤销！\n"
                "请确保您已经备份重要文件。\n\n"
                "是否继续？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return
        
        # 开始真正的批量分割处理
        self._start_multi_folder_split(
            selected_folders, output_folder, (min_duration, max_duration),
            resolution, bitrate, quality, save_metadata, delete_original
        )
    
    def _start_multi_folder_split(self, selected_folders, output_folder, duration_range, 
                                  resolution, bitrate, quality, save_metadata, delete_original):
        """开始多文件夹批处理分割"""
        # 检查BatchProcessor是否支持分割任务
        if not hasattr(self.batch_processor, 'add_split_job'):
            # 如果BatchProcessor不支持分割，回退到单个处理但要循环处理所有文件夹
            QMessageBox.information(
                self, 
                "批处理模式", 
                f"将依次处理 {len(selected_folders)} 个文件夹。\n\n"
                "处理完成后会有提示。"
            )
            self._start_sequential_split(
                selected_folders, output_folder, duration_range,
                resolution, bitrate, quality, save_metadata, delete_original
            )
            return
        
        # 获取质量设置  
        quality_map = {"高质量": "high", "中等质量": "medium", "快速编码": "low"}
        quality_str = quality_map.get(quality, "medium")
        
        # 为每个选中文件夹创建批处理任务
        success_count = 0
        for folder_info in selected_folders:
            # 为每个文件夹创建独立的输出子文件夹，保持原文件夹名称
            folder_name = os.path.basename(folder_info.path)
            folder_output = os.path.join(output_folder, folder_name)
            os.makedirs(folder_output, exist_ok=True)
            
            success = self.batch_processor.add_split_job(
                folder_info.path,
                folder_output,
                duration_range,
                resolution,
                bitrate,
                quality_str,
                save_metadata,
                delete_original
            )
            
            if success:
                success_count += 1
            else:
                QMessageBox.warning(
                    self, "添加任务失败", 
                    f"无法添加文件夹 '{folder_name}' 到批处理队列"
                )
        
        if success_count == 0:
            QMessageBox.warning(self, "批处理失败", "没有成功添加任何处理任务")
            return
        
        # 启动批处理
        self.batch_processor.start_processing()
        if success_count > 0:
            QMessageBox.information(
                self, "批处理启动成功",
                f"成功启动批处理，共 {success_count} 个文件夹待处理"
            )
        else:
            QMessageBox.warning(self, "启动失败", "无法启动批处理")
    
    def _start_sequential_split(self, selected_folders, output_folder, duration_range,
                               resolution, bitrate, quality, save_metadata, delete_original):
        """顺序处理分割（如果BatchProcessor不支持分割任务）"""
        # 这是一个简化的顺序处理，一个接一个处理文件夹
        # 开始处理第一个文件夹
        if selected_folders:
            self._current_split_folders = selected_folders.copy()
            self._current_split_settings = {
                'output_folder': output_folder,
                'duration_range': duration_range,
                'resolution': resolution,
                'bitrate': bitrate,
                'quality': quality,
                'save_metadata': save_metadata,
                'delete_original': delete_original
            }
            self._process_next_split_folder()
    
    def _process_next_split_folder(self):
        """处理下一个分割文件夹"""
        if not hasattr(self, '_current_split_folders') or not self._current_split_folders:
            # 所有文件夹处理完成
            QMessageBox.information(
                self, 
                "处理完成", 
                "🎉 视频分割批处理已完成！\n\n所有选中的文件夹都已处理完毕，请查看输出文件夹。"
            )
            return
        
        # 获取下一个文件夹
        current_folder = self._current_split_folders.pop(0)
        settings = self._current_split_settings
        
        # 为当前文件夹创建输出目录
        folder_name = os.path.basename(current_folder.path)
        folder_output = os.path.join(settings['output_folder'], folder_name)
        os.makedirs(folder_output, exist_ok=True)
        
        # 启动分割处理
        self._start_split_processing(
            current_folder.path, folder_output, settings['duration_range'],
            settings['resolution'], settings['bitrate'], settings['quality'], 
            settings['save_metadata'], settings['delete_original']
        )
    
    def _get_audio_settings(self):
        """获取音频设置"""
        return {
            'keep_original': self.keep_original_check.isChecked(),
            'original_volume': self.original_volume_slider.value(),
            'replace_audio': self.replace_audio_check.isChecked(),
            'replace_audio_path': self.replace_audio_edit.text(),
            'replace_audio_is_folder': self.replace_audio_type_combo.currentText() == "选择文件夹",
            'replace_volume': self.replace_volume_slider.value(),
            'background_audio': self.background_audio_check.isChecked(),
            'background_audio_path': self.background_audio_edit.text(),
            'background_audio_is_folder': self.background_audio_type_combo.currentText() == "选择文件夹",
            'background_volume': self.background_volume_slider.value()
        }
    
    def _validate_audio_settings(self, audio_settings):
        """验证音频设置"""
        # 检查替换音频路径是否存在
        if audio_settings['replace_audio'] and audio_settings['replace_audio_path']:
            if audio_settings['replace_audio_is_folder']:
                if not os.path.isdir(audio_settings['replace_audio_path']):
                    QMessageBox.warning(self, "音频错误", "请选择有效的替换音频文件夹")
                    return False
                # 检查文件夹内是否有音频文件
                audio_files = self._get_audio_files_from_folder(audio_settings['replace_audio_path'])
                if not audio_files:
                    QMessageBox.warning(self, "音频错误", "替换音频文件夹中没有找到音频文件")
                    return False
            else:
                if not os.path.isfile(audio_settings['replace_audio_path']):
                    QMessageBox.warning(self, "音频错误", "请选择有效的替换音频文件")
                    return False
        elif audio_settings['replace_audio']:
            QMessageBox.warning(self, "音频错误", "请选择替换音频文件或文件夹")
            return False
        
        # 检查背景音路径是否存在
        if audio_settings['background_audio'] and audio_settings['background_audio_path']:
            if audio_settings['background_audio_is_folder']:
                if not os.path.isdir(audio_settings['background_audio_path']):
                    QMessageBox.warning(self, "音频错误", "请选择有效的背景音文件夹")
                    return False
                # 检查文件夹内是否有音频文件
                audio_files = self._get_audio_files_from_folder(audio_settings['background_audio_path'])
                if not audio_files:
                    QMessageBox.warning(self, "音频错误", "背景音文件夹中没有找到音频文件")
                    return False
            else:
                if not os.path.isfile(audio_settings['background_audio_path']):
                    QMessageBox.warning(self, "音频错误", "请选择有效的背景音文件")
                    return False
        elif audio_settings['background_audio']:
            QMessageBox.warning(self, "音频错误", "请选择背景音文件或文件夹")
            return False
        
        # 检查是否至少有一个音频源
        if not audio_settings['keep_original'] and not audio_settings['replace_audio'] and not audio_settings['background_audio']:
            reply = QMessageBox.question(
                self, "无音频源", 
                "您选择不保留原音频、不替换音频也不添加背景音，\n"
                "生成的视频将没有任何声音。是否继续？",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.No:
                return False
        
        return True
    
    def _get_audio_files_from_folder(self, folder_path):
        """从文件夹中获取音频文件列表"""
        audio_extensions = ('.mp3', '.wav', '.ogg', '.flac', '.m4a', '.aac', '.wma')
        try:
            audio_files = [f for f in os.listdir(folder_path) 
                          if f.lower().endswith(audio_extensions)]
            return [os.path.join(folder_path, f) for f in audio_files]
        except Exception:
            return []
    
    def _check_video_files(self, input_folder, videos_per_output, total_outputs, reuse_material):
        """检查视频文件"""
        video_extensions = ('.mp4', '.avi', '.mov', '.mkv', '.flv', '.wmv', '.mpeg', '.mpg')
        video_files = [f for f in os.listdir(input_folder) 
                      if f.lower().endswith(video_extensions)]
        if not video_files:
            QMessageBox.warning(self, "无视频文件", "输入文件夹中没有找到视频文件")
            return False
        
        # 检查是否有足够的视频文件
        if not reuse_material and len(video_files) < videos_per_output * total_outputs:
            reply = QMessageBox.question(self, "文件不足", 
                                        f"可用视频文件不足（需要{videos_per_output * total_outputs}个，找到{len(video_files)}个）。\n"
                                        "是否允许重复使用素材？",
                                        QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.No:
                return False
            self.reuse_checkbox.setChecked(True)
        
        return True
    
    def _start_video_processing(self, input_folder, output_folder, videos_per_output, 
                               total_outputs, resolution, bitrate, reuse_material, audio_settings):
        """启动视频处理"""
        # 禁用按钮
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.setText("取消")
        
        # 重置取消状态和进度
        self._cancel_requested = False
        self._current_progress = 0.0
        self._target_progress = 0.0
        self.progress_bar.setValue(0)
        self.progress_label.setText("开始处理...")
        
        # 获取质量设置
        quality_map = {"高质量": "high", "中等质量": "medium", "快速编码": "low"}
        quality = quality_map.get(self.quality_combo.currentText(), "high")
        
        # 创建并启动处理器线程
        try:
            # 根据GPU设置选择处理器
            if self.use_gpu_checkbox.isChecked() and self.gpu_config_manager.gpu_info['use_gpu']:
                # 使用GPU加速处理器
                gpu_settings = self.gpu_config_manager.gpu_info.copy()
                gpu_settings['quality'] = quality
                
                self.processor = FFmpegGPUProcessor(
                    input_folder, output_folder, videos_per_output, total_outputs,
                    resolution, bitrate, reuse_material, audio_settings, gpu_settings
                )
                
                # 显示性能预估
                self._show_performance_estimate(resolution, total_outputs * videos_per_output * 30)  # 假设每个视频30秒
            else:
                # 使用传统MoviePy处理器
                self.processor = VideoProcessor(
                    input_folder, output_folder, videos_per_output, total_outputs,
                    resolution, bitrate, reuse_material, audio_settings
                )
            
            self.processor.progress_updated.connect(self.update_progress)
            self.processor.process_finished.connect(self.process_finished)
            
            # 连接详细进度信号（如果支持）
            if hasattr(self.processor, 'detailed_progress_updated'):
                self.processor.detailed_progress_updated.connect(self.update_detailed_progress)
            
            self.processor.start()
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))
            self.progress_label.setText("启动失败")
            self.reset_ui()
    
    def _start_split_processing(self, input_path, output_folder, duration_range, 
                               resolution, bitrate, quality, save_metadata, delete_original):
        """启动视频分割处理"""
        # 禁用按钮
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.setText("取消")
        
        # 重置取消状态和进度
        self._cancel_requested = False
        self._current_progress = 0.0
        self._target_progress = 0.0
        self.progress_bar.setValue(0)
        self.progress_label.setText("开始分割...")
        
        # 创建并启动分割器线程
        try:
            # 强制使用GPU加速分割
            use_gpu = True
            
            self.splitter = VideoSplitter(
                input_path, output_folder, duration_range,
                resolution, bitrate, use_gpu, quality, save_metadata, delete_original
            )
            
            self.splitter.progress_updated.connect(self.update_progress)
            self.splitter.process_finished.connect(self.process_finished)
            
            # 连接详细进度信号
            if hasattr(self.splitter, 'detailed_progress_updated'):
                self.splitter.detailed_progress_updated.connect(self.update_detailed_progress)
            
            self.splitter.start()
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))
            self.progress_label.setText("启动失败")
            self.reset_ui()
    
    def cancel_processing(self):
        """取消视频处理（带防抖）"""
        current_time = time.time() * 1000  # 转换为毫秒
        
        # 防抖检查
        if current_time - self._last_cancel_time < self._cancel_debounce_ms:
            return  # 忽略过于频繁的取消请求
        
        self._last_cancel_time = current_time
        
        if self._cancel_requested:
            return  # 已经请求过取消，避免重复处理
        
        # 检查是否在批处理模式
        if self.batch_mode == BatchMode.MULTI_FOLDER and self.batch_processor.running:
            self._cancel_requested = True
            
            # 更新UI状态
            self.cancel_btn.setText("取消中...")
            self.cancel_btn.setEnabled(False)
            self.progress_label.setText("正在取消批处理...")
            
            # 停止批处理
            self.batch_processor.cancel_batch()
            
            # 启动超时检查
            QTimer.singleShot(3000, self._check_cancel_timeout)  # 3秒超时
        
        # 取消视频合成处理器
        elif self.processor and self.processor.isRunning():
            self._cancel_requested = True
            
            # 更新UI状态
            self.cancel_btn.setText("取消中...")
            self.cancel_btn.setEnabled(False)
            self.progress_label.setText("正在取消处理...")
            
            # 停止处理器
            self.processor.stop()
            
            # 启动超时检查
            QTimer.singleShot(3000, self._check_cancel_timeout)  # 3秒超时
        
        # 取消视频分割处理器
        elif self.splitter and self.splitter.isRunning():
            self._cancel_requested = True
            
            # 更新UI状态
            self.cancel_btn.setText("取消中...")
            self.cancel_btn.setEnabled(False)
            self.progress_label.setText("正在取消分割...")
            
            # 停止分割器
            self.splitter.stop()
            
            # 启动超时检查
            QTimer.singleShot(3000, self._check_cancel_timeout)  # 3秒超时
    
    def update_progress(self, value):
        """更新进度条（整数值，兼容旧接口）"""
        self._target_progress = float(value)
        self._start_smooth_progress_update()
        
        # 更新进度标签
        self.progress_label.setText(f"处理中... {int(value)}%")
    
    def update_detailed_progress(self, progress):
        """更新详细进度（浮点值 0.0-1.0）"""
        self._target_progress = progress * 100.0
        self._start_smooth_progress_update()
        
        # 更新进度标签
        self.progress_label.setText(f"处理中... {progress * 100:.1f}%")
    
    def _start_smooth_progress_update(self):
        """启动平滑进度更新"""
        if not self._progress_timer.isActive():
            self._progress_timer.start(self._progress_update_interval)
    
    def _update_smooth_progress(self):
        """平滑更新进度条"""
        # 计算进度差值
        diff = self._target_progress - self._current_progress
        
        if abs(diff) < 0.1:  # 差值很小，直接设置目标值
            self._current_progress = self._target_progress
            self._progress_timer.stop()
        else:
            # 平滑过渡
            self._current_progress += diff * 0.2  # 每次移动20%的差距
        
        # 更新进度条
        self.progress_bar.setValue(int(self._current_progress))
    
    def process_finished(self, message):
        """处理完成回调"""
        # 停止平滑进度更新
        self._progress_timer.stop()
        
        # 检查是否是顺序分割处理
        if hasattr(self, '_current_split_folders') and self._current_split_folders:
            # 还有文件夹要处理，继续下一个
            self._process_next_split_folder()
            return
        
        # 根据是否取消显示不同消息
        if self._cancel_requested:
            if "已取消" in message or "取消" in message:
                self.progress_label.setText("操作已取消")
                QMessageBox.information(self, "已取消", message)
            else:
                self.progress_label.setText("取消失败")
                QMessageBox.warning(self, "取消失败", f"无法完全取消操作：\n{message}")
        else:
            if "完成" in message:
                self.progress_bar.setValue(100)
                self.progress_label.setText("处理完成！")
                # 如果是顺序分割的最后一个，显示特殊完成消息
                if hasattr(self, '_current_split_folders'):
                    QMessageBox.information(
                        self, 
                        "处理完成", 
                        "🎉 视频分割批处理已完成！\n\n所有选中的文件夹都已处理完毕，请查看输出文件夹。"
                    )
                    # 清理顺序处理状态
                    if hasattr(self, '_current_split_folders'):
                        delattr(self, '_current_split_folders')
                    if hasattr(self, '_current_split_settings'):
                        delattr(self, '_current_split_settings')
                else:
                    QMessageBox.information(self, "完成", message)
            else:
                self.progress_label.setText("处理出错")
                QMessageBox.critical(self, "错误", message)
        
        self.reset_ui()
    
    def reset_ui(self):
        """重置UI状态"""
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setText("取消")
        
        # 重置取消状态
        self._cancel_requested = False
        
        # 停止平滑进度更新
        self._progress_timer.stop()
        
        # 重置进度
        if not self._cancel_requested:  # 只有在非取消情况下才重置进度
            self._current_progress = 0.0
            self._target_progress = 0.0
            self.progress_bar.setValue(0)
            self.progress_label.setText("准备就绪")
        
        self.processor = None
        self.splitter = None
    
    def _check_cancel_timeout(self):
        """检查取消操作是否超时"""
        if self._cancel_requested:
            # 检查合成处理器
            if self.processor and self.processor.isRunning():
                # 取消超时，强制重置UI
                QMessageBox.warning(
                    self, "取消超时", 
                    "取消操作超时，可能存在孤儿进程。\n建议重启应用程序。"
                )
                self.reset_ui()
            # 检查分割处理器
            elif self.splitter and self.splitter.isRunning():
                # 取消超时，强制重置UI
                QMessageBox.warning(
                    self, "取消超时", 
                    "取消分割操作超时，可能存在孤儿进程。\n建议重启应用程序。"
                )
                self.reset_ui()

    def load_config(self):
        """加载配置"""
        config = self.config_manager.load_config()
        
        # 委托给简化标签页来加载配置
        if hasattr(self, 'simple_merge_tab'):
            self.simple_merge_tab.load_config(config)
        if hasattr(self, 'simple_split_tab'):
            self.simple_split_tab.load_config(config)

    def save_config(self):
        """保存配置"""
        config = {}
        
        # 从简化标签页收集配置
        if hasattr(self, 'simple_merge_tab'):
            config.update(self.simple_merge_tab.get_config())
        if hasattr(self, 'simple_split_tab'):
            config.update(self.simple_split_tab.get_config())
            
        self.config_manager.save_config(config)

    def closeEvent(self, event):
        """窗口关闭事件，保存配置并清理资源"""
        # 保存配置
        self.save_config()
        
        # 清理批处理器资源
        if hasattr(self, 'batch_processor'):
            self.batch_processor.cleanup()
        
        super().closeEvent(event)
    
    def _on_config_changed(self):
        """配置变化时自动保存"""
        try:
            self.save_config()
            print("[MainWindow] 音频配置已自动保存")
        except Exception as e:
            print(f"[MainWindow] 保存配置时发生错误: {e}")
    
    def _update_gpu_status(self):
        """更新GPU状态显示"""
        gpu_info = self.gpu_config_manager.get_gpu_status()
        
        if gpu_info['gpu_detected']:
            status_text = f"✅ {gpu_info['vendor'].upper()} GPU: {gpu_info['model']}\n"
            status_text += f"编码器: {gpu_info['hardware_encoder']}"
            if gpu_info['hardware_decoder']:
                status_text += f" | 解码器: {gpu_info['hardware_decoder']}"
            self.gpu_status_label.setText(status_text)
            self.gpu_status_label.setStyleSheet("color: #2E7D32; font-size: 11px;")  # 绿色
        else:
            self.gpu_status_label.setText("⚠️ 未检测到GPU硬件加速支持，将使用CPU编码")
            self.gpu_status_label.setStyleSheet("color: #F57C00; font-size: 11px;")  # 橙色
    
    def _on_gpu_setting_changed(self, enabled):
        """GPU设置变化时的回调"""
        if enabled and not self.gpu_config_manager.gpu_info['use_gpu']:
            QMessageBox.information(
                self, 
                "GPU加速", 
                "系统未检测到GPU硬件加速支持。\n将继续使用CPU编码。"
            )
            self.use_gpu_checkbox.setChecked(False)
        
        self._update_gpu_status()
    
    def _show_performance_estimate(self, resolution, estimated_duration):
        """显示性能预估"""
        try:
            perf_info = self.gpu_config_manager.get_performance_estimate(estimated_duration, resolution)
            
            if perf_info['gpu_acceleration']:
                speed_text = f"预计加速 {perf_info['estimated_speed_multiplier']:.1f}x"
                time_text = f"预计处理时间: {perf_info['estimated_processing_time']:.1f}秒"
                encoder_text = f"使用编码器: {perf_info['encoder']}"
                
                QMessageBox.information(
                    self,
                    "性能预估",
                    f"🚀 GPU加速已启用\n\n{speed_text}\n{time_text}\n{encoder_text}"
                )
        except Exception:
            pass  # 静默处理预估错误
    
    def reset_dedup_state(self):
        """清空去重状态"""
        from PyQt5.QtWidgets import QMessageBox
        import os
        from core.sequence_selector import SequenceDiversitySelector
        
        # 确认操作
        reply = QMessageBox.question(
            self,
            "确认清空",
            "确定要清空去重记录吗？\n\n这将重置所有已记录的素材组合历史，\n下次生成视频时将重新开始去重逻辑。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        try:
            # 获取当前输入文件夹
            input_folder = self.input_folder_edit.text().strip()
            if not input_folder:
                QMessageBox.warning(self, "警告", "请先选择输入文件夹")
                return
            
            # 使用与SequenceDiversitySelector相同的路径生成逻辑
            from core.sequence_selector import SequenceDiversitySelector
            dummy_selector = SequenceDiversitySelector(["dummy"], 1)  # 临时实例用于生成路径
            persistence_file = dummy_selector.get_persistence_file_path(input_folder)
            
            # 删除持久化文件
            if os.path.exists(persistence_file):
                os.remove(persistence_file)
                QMessageBox.information(
                    self,
                    "清空成功",
                    f"已清空 '{os.path.basename(input_folder)}' 的去重记录\n\n下次生成视频时将重新开始去重逻辑。"
                )
            else:
                QMessageBox.information(
                    self,
                    "无记录",
                    f"'{os.path.basename(input_folder)}' 暂无去重记录"
                )
                
        except Exception as e:
            QMessageBox.critical(
                self,
                "错误",
                f"清空去重记录时发生错误：\n{str(e)}"
            )
    
    def manage_dedup_states(self):
        """管理去重状态文件"""
        from PyQt5.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem, QHeaderView
        from core.sequence_selector import SequenceDiversitySelector
        import time
        
        # 创建管理对话框
        dialog = QDialog(self)
        dialog.setWindowTitle("去重记录管理")
        dialog.setGeometry(200, 200, 800, 500)
        
        layout = QVBoxLayout(dialog)
        
        # 获取所有状态文件
        states = SequenceDiversitySelector.list_all_states()
        
        if not states:
            QMessageBox.information(self, "无记录", "当前没有任何去重记录文件")
            return
        
        # 创建表格
        table = QTableWidget(len(states), 6)
        table.setHorizontalHeaderLabels([
            "文件夹名", "哈希ID", "已用序列数", "素材数", "每视频素材数", "最后修改时间"
        ])
        
        # 填充表格数据
        for i, state in enumerate(states):
            filename = state['filename']
            # 解析文件名：{folder_name}_{hash}_dedup_state.json
            name_parts = filename.replace('_dedup_state.json', '').rsplit('_', 1)
            folder_name = name_parts[0] if len(name_parts) > 1 else filename
            hash_id = name_parts[1] if len(name_parts) > 1 else "legacy"
            
            table.setItem(i, 0, QTableWidgetItem(folder_name))
            table.setItem(i, 1, QTableWidgetItem(hash_id))
            table.setItem(i, 2, QTableWidgetItem(str(state['used_sequences_count'])))
            table.setItem(i, 3, QTableWidgetItem(str(state['materials_count'])))
            table.setItem(i, 4, QTableWidgetItem(str(state['per_video'])))
            
            # 格式化时间
            time_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(state['last_modified']))
            table.setItem(i, 5, QTableWidgetItem(time_str))
        
        # 调整表格列宽
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        
        layout.addWidget(table)
        
        # 添加操作按钮
        btn_layout = QHBoxLayout()
        
        # 清理旧文件按钮
        cleanup_btn = QPushButton("清理30天前的记录")
        cleanup_btn.clicked.connect(lambda: self._cleanup_old_states(dialog))
        btn_layout.addWidget(cleanup_btn)
        
        # 删除选中按钮
        delete_btn = QPushButton("删除选中记录")
        delete_btn.clicked.connect(lambda: self._delete_selected_states(table, dialog))
        btn_layout.addWidget(delete_btn)
        
        # 关闭按钮
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(dialog.close)
        btn_layout.addWidget(close_btn)
        
        layout.addLayout(btn_layout)
        
        dialog.exec_()
    
    def _cleanup_old_states(self, parent_dialog):
        """清理旧的状态文件"""
        from PyQt5.QtWidgets import QMessageBox
        from core.sequence_selector import SequenceDiversitySelector
        
        reply = QMessageBox.question(
            parent_dialog,
            "确认清理",
            "确定要清理30天前的去重记录文件吗？\n\n此操作不可撤销。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            try:
                SequenceDiversitySelector.cleanup_old_states(30)
                QMessageBox.information(parent_dialog, "清理完成", "已清理30天前的去重记录文件")
                parent_dialog.close()
            except Exception as e:
                QMessageBox.critical(parent_dialog, "清理失败", f"清理过程中发生错误：\n{str(e)}")
    
    def _delete_selected_states(self, table, parent_dialog):
        """删除选中的状态文件"""
        from PyQt5.QtWidgets import QMessageBox
        from core.sequence_selector import SequenceDiversitySelector
        import os
        
        selected_rows = set()
        for item in table.selectedItems():
            selected_rows.add(item.row())
        
        if not selected_rows:
            QMessageBox.warning(parent_dialog, "未选中", "请先选择要删除的记录")
            return
        
        reply = QMessageBox.question(
            parent_dialog,
            "确认删除",
            f"确定要删除选中的 {len(selected_rows)} 个去重记录文件吗？\n\n此操作不可撤销。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            try:
                states = SequenceDiversitySelector.list_all_states()
                deleted_count = 0
                
                for row in selected_rows:
                    if row < len(states):
                        file_path = states[row]['file_path']
                        if os.path.exists(file_path):
                            os.remove(file_path)
                            deleted_count += 1
                
                QMessageBox.information(
                    parent_dialog, 
                    "删除完成", 
                    f"已删除 {deleted_count} 个去重记录文件"
                )
                parent_dialog.close()
            except Exception as e:
                QMessageBox.critical(parent_dialog, "删除失败", f"删除过程中发生错误：\n{str(e)}")
    
    def _create_split_input_settings(self, layout):
        """创建分割输入设置区域"""
        input_group = QGroupBox("分割输入设置")
        input_layout = QVBoxLayout()
        
        # 输入类型选择
        input_type_layout = QHBoxLayout()
        input_type_layout.addWidget(QLabel("输入类型:"))
        self.split_input_type_combo = QComboBox()
        self.split_input_type_combo.addItems(["选择文件", "选择文件夹"])
        self.split_input_type_combo.currentTextChanged.connect(self.on_split_input_type_changed)
        input_type_layout.addWidget(self.split_input_type_combo)
        input_layout.addLayout(input_type_layout)
        
        # 输入路径选择
        input_path_layout = QHBoxLayout()
        input_path_layout.addWidget(QLabel("输入路径:"))
        self.split_input_edit = QLineEdit()
        self.split_input_edit.setReadOnly(True)
        input_path_layout.addWidget(self.split_input_edit, 1)
        self.split_input_btn = QPushButton("浏览...")
        self.split_input_btn.clicked.connect(self.browse_split_input)
        input_path_layout.addWidget(self.split_input_btn)
        input_layout.addLayout(input_path_layout)
        
        # 输出文件夹选择
        output_path_layout = QHBoxLayout()
        output_path_layout.addWidget(QLabel("输出文件夹:"))
        self.split_output_edit = QLineEdit()
        self.split_output_edit.setReadOnly(True)
        output_path_layout.addWidget(self.split_output_edit, 1)
        self.split_output_btn = QPushButton("浏览...")
        self.split_output_btn.clicked.connect(self.browse_split_output)
        output_path_layout.addWidget(self.split_output_btn)
        input_layout.addLayout(output_path_layout)
        
        input_group.setLayout(input_layout)
        layout.addWidget(input_group)
    
    def _create_split_duration_settings(self, layout):
        """创建分割时长设置区域"""
        duration_group = QGroupBox("分割时长设置")
        duration_layout = QVBoxLayout()
        
        # 最小时长设置
        min_duration_layout = QHBoxLayout()
        min_duration_layout.addWidget(QLabel("最小分割时长 (秒):"))
        self.split_min_duration_spin = QDoubleSpinBox()
        self.split_min_duration_spin.setMinimum(0.1)
        self.split_min_duration_spin.setMaximum(3600.0)
        self.split_min_duration_spin.setValue(2.0)
        self.split_min_duration_spin.setDecimals(1)
        self.split_min_duration_spin.setSingleStep(0.1)
        min_duration_layout.addWidget(self.split_min_duration_spin)
        duration_layout.addLayout(min_duration_layout)
        
        # 最大时长设置
        max_duration_layout = QHBoxLayout()
        max_duration_layout.addWidget(QLabel("最大分割时长 (秒):"))
        self.split_max_duration_spin = QDoubleSpinBox()
        self.split_max_duration_spin.setMinimum(0.1)
        self.split_max_duration_spin.setMaximum(3600.0)
        self.split_max_duration_spin.setValue(4.0)
        self.split_max_duration_spin.setDecimals(1)
        self.split_max_duration_spin.setSingleStep(0.1)
        max_duration_layout.addWidget(self.split_max_duration_spin)
        duration_layout.addLayout(max_duration_layout)
        
        # 添加说明
        help_label = QLabel("说明：每个片段的时长将在最小和最大时长之间随机选择。\n"
                           "不满足最小时长的剩余片段将被跳过。")
        help_label.setStyleSheet("color: #666; font-size: 11px;")
        help_label.setWordWrap(True)
        duration_layout.addWidget(help_label)
        
        duration_group.setLayout(duration_layout)
        layout.addWidget(duration_group)
    
    def _create_split_output_settings(self, layout):
        """创建分割输出设置区域"""
        output_group = QGroupBox("输出设置")
        output_layout = QVBoxLayout()
        
        # 分辨率设置
        resolution_layout = QHBoxLayout()
        self.split_keep_resolution_check = QCheckBox("保持原分辨率")
        self.split_keep_resolution_check.setChecked(True)
        self.split_keep_resolution_check.toggled.connect(self.toggle_split_resolution)
        resolution_layout.addWidget(self.split_keep_resolution_check)
        
        resolution_layout.addWidget(QLabel("输出分辨率:"))
        self.split_resolution_combo = QComboBox()
        self.split_resolution_combo.addItems(["1920x1080", "1080x1920", "1280x720", "2560x1440", "3840x2160"])
        self.split_resolution_combo.setEnabled(False)
        resolution_layout.addWidget(self.split_resolution_combo)
        output_layout.addLayout(resolution_layout)
        
        # 码率设置
        bitrate_layout = QHBoxLayout()
        self.split_auto_bitrate_check = QCheckBox("自动码率")
        self.split_auto_bitrate_check.setChecked(True)
        self.split_auto_bitrate_check.toggled.connect(self.toggle_split_bitrate)
        bitrate_layout.addWidget(self.split_auto_bitrate_check)
        
        bitrate_layout.addWidget(QLabel("输出码率:"))
        self.split_bitrate_edit = QLineEdit("5000k")
        self.split_bitrate_edit.setEnabled(False)
        bitrate_layout.addWidget(self.split_bitrate_edit)
        output_layout.addLayout(bitrate_layout)
        
        # 质量设置
        quality_layout = QHBoxLayout()
        quality_layout.addWidget(QLabel("编码质量:"))
        self.split_quality_combo = QComboBox()
        self.split_quality_combo.addItems(["高质量", "中等质量", "快速编码"])
        self.split_quality_combo.setCurrentText("中等质量")
        quality_layout.addWidget(self.split_quality_combo)
        output_layout.addLayout(quality_layout)
        
        # 元数据保存设置
        metadata_layout = QHBoxLayout()
        self.split_save_metadata_check = QCheckBox("保存片段元数据（用于合成时去重）")
        self.split_save_metadata_check.setChecked(True)
        self.split_save_metadata_check.setToolTip("保存到segments_metadata.json文件，用于合成时避免同一原视频的片段出现在同一合成视频中")
        metadata_layout.addWidget(self.split_save_metadata_check)
        output_layout.addLayout(metadata_layout)
        
        # 删除原视频设置
        delete_layout = QHBoxLayout()
        self.split_delete_original_check = QCheckBox("分割完成后删除原视频文件")
        self.split_delete_original_check.setChecked(False)
        self.split_delete_original_check.setToolTip("警告：删除原视频文件后无法恢复，请确保分割结果满意后再启用此选项")
        self.split_delete_original_check.setStyleSheet("color: #FF6B35;")  # 橙色警告色
        delete_layout.addWidget(self.split_delete_original_check)
        output_layout.addLayout(delete_layout)
        
        # 文件命名说明
        naming_label = QLabel("输出文件命名格式：原文件名-1.mp4, 原文件名-2.mp4 ...")
        naming_label.setStyleSheet("color: #666; font-size: 11px;")
        output_layout.addWidget(naming_label)
        
        output_group.setLayout(output_layout)
        layout.addWidget(output_group)
    
    def on_split_input_type_changed(self):
        """分割输入类型改变时清空路径"""
        self.split_input_edit.setText("")
    
    def toggle_split_resolution(self, enabled):
        """切换分割分辨率设置"""
        self.split_resolution_combo.setEnabled(not enabled)
    
    def toggle_split_bitrate(self, enabled):
        """切换分割码率设置"""
        self.split_bitrate_edit.setEnabled(not enabled)
    
    def browse_split_input(self):
        """浏览选择分割输入路径"""
        if self.split_input_type_combo.currentText() == "选择文件":
            file, _ = QFileDialog.getOpenFileName(
                self, "选择视频文件", "", 
                "视频文件 (*.mp4 *.avi *.mov *.mkv *.flv *.wmv *.mpeg *.mpg)"
            )
            if file:
                self.split_input_edit.setText(file)
        else:  # 选择文件夹
            folder = QFileDialog.getExistingDirectory(self, "选择视频文件夹")
            if folder:
                self.split_input_edit.setText(folder)
    
    def browse_split_output(self):
        """浏览选择分割输出文件夹"""
        folder = QFileDialog.getExistingDirectory(self, "选择输出文件夹")
        if folder:
            self.split_output_edit.setText(folder)
    
    def _on_mode_changed(self, button):
        """处理模式切换"""
        if button == self.single_mode_radio:
            self.batch_mode = BatchMode.SINGLE_FOLDER
            self.single_folder_widget.setVisible(True)
            self.multi_folder_widget.setVisible(False)
        else:  # multi_mode_radio
            self.batch_mode = BatchMode.MULTI_FOLDER
            self.single_folder_widget.setVisible(False)
            self.multi_folder_widget.setVisible(True)
        
        # 调整窗口大小
        self.adjustSize()
    
    def browse_multi_output(self):
        """浏览选择多文件夹模式的统一输出文件夹"""
        folder = QFileDialog.getExistingDirectory(self, "选择统一输出文件夹")
        if folder:
            self.multi_output_folder_edit.setText(folder)
    
    def _on_multi_folders_changed(self, folders):
        """多文件夹列表变化回调"""
        # 更新UI状态
        has_folders = len(folders) > 0
        # 这里可以根据需要更新按钮状态等
        pass
    
    def _setup_batch_signals(self):
        """设置批处理信号连接"""
        # 连接批处理器信号（使用队列连接确保线程安全）
        self.batch_processor.job_started.connect(self._on_batch_job_started, Qt.QueuedConnection)
        self.batch_processor.job_progress.connect(self._on_batch_job_progress, Qt.QueuedConnection)
        self.batch_processor.job_completed.connect(self._on_batch_job_completed, Qt.QueuedConnection)
        self.batch_processor.job_failed.connect(self._on_batch_job_failed, Qt.QueuedConnection)
        self.batch_processor.job_paused.connect(self._on_batch_job_paused, Qt.QueuedConnection)
        self.batch_processor.job_resumed.connect(self._on_batch_job_resumed, Qt.QueuedConnection)
        self.batch_processor.job_cancelled.connect(self._on_batch_job_cancelled, Qt.QueuedConnection)
        
        self.batch_processor.batch_started.connect(self._on_batch_started, Qt.QueuedConnection)
        self.batch_processor.batch_completed.connect(self._on_batch_completed, Qt.QueuedConnection)
        self.batch_processor.batch_paused.connect(self._on_batch_paused, Qt.QueuedConnection)
        self.batch_processor.batch_resumed.connect(self._on_batch_resumed, Qt.QueuedConnection)
        self.batch_processor.batch_cancelled.connect(self._on_batch_cancelled, Qt.QueuedConnection)
        
        self.batch_processor.overall_progress.connect(self._on_batch_overall_progress, Qt.QueuedConnection)
    
    def _on_batch_job_started(self, folder_path):
        """批处理任务开始回调"""
        if self.multi_folder_manager:
            self.multi_folder_manager.update_folder_progress(folder_path, 0.0, FolderStatus.PROCESSING)
        
        # 更新简化界面
        if hasattr(self, 'simple_merge_tab'):
            self.simple_merge_tab.on_job_started(folder_path)
        if hasattr(self, 'simple_split_tab'):
            self.simple_split_tab.on_job_started(folder_path)
    
    def _on_batch_job_progress(self, folder_path, progress):
        """批处理任务进度回调"""
        if self.multi_folder_manager:
            self.multi_folder_manager.update_folder_progress(folder_path, progress, FolderStatus.PROCESSING)
        
        # 更新简化界面
        if hasattr(self, 'simple_merge_tab'):
            self.simple_merge_tab.on_job_progress(folder_path, progress)
        if hasattr(self, 'simple_split_tab'):
            self.simple_split_tab.on_job_progress(folder_path, progress)
    
    def _on_batch_job_completed(self, folder_path, message):
        """批处理任务完成回调"""
        if self.multi_folder_manager:
            self.multi_folder_manager.update_folder_progress(folder_path, 1.0, FolderStatus.COMPLETED)
        
        # 更新简化界面
        if hasattr(self, 'simple_merge_tab'):
            self.simple_merge_tab.on_job_completed(folder_path, message)
        if hasattr(self, 'simple_split_tab'):
            self.simple_split_tab.on_job_completed(folder_path, message)
    
    def _on_batch_job_failed(self, folder_path, error_message):
        """批处理任务失败回调"""
        if self.multi_folder_manager:
            self.multi_folder_manager.update_folder_progress(folder_path, 0.0, FolderStatus.FAILED)
        
        # 更新简化界面
        if hasattr(self, 'simple_merge_tab'):
            self.simple_merge_tab.on_job_failed(folder_path, error_message)
        if hasattr(self, 'simple_split_tab'):
            self.simple_split_tab.on_job_failed(folder_path, error_message)
        
        # 显示错误消息
        QMessageBox.warning(
            self, "处理失败", 
            f"文件夹 '{os.path.basename(folder_path)}' 处理失败：\n{error_message}"
        )
    
    def _on_batch_job_paused(self, folder_path):
        """批处理任务暂停回调"""
        if self.multi_folder_manager:
            folder_info = self.multi_folder_manager._find_folder_by_path(folder_path)
            if folder_info:
                self.multi_folder_manager.update_folder_progress(folder_path, folder_info.progress, FolderStatus.PAUSED)
    
    def _on_batch_job_resumed(self, folder_path):
        """批处理任务恢复回调"""
        if self.multi_folder_manager:
            folder_info = self.multi_folder_manager._find_folder_by_path(folder_path)
            if folder_info:
                self.multi_folder_manager.update_folder_progress(folder_path, folder_info.progress, FolderStatus.PROCESSING)
    
    def _on_batch_job_cancelled(self, folder_path):
        """批处理任务取消回调"""
        if self.multi_folder_manager:
            folder_info = self.multi_folder_manager._find_folder_by_path(folder_path)
            if folder_info:
                self.multi_folder_manager.update_folder_progress(folder_path, folder_info.progress, FolderStatus.CANCELLED)
    
    def _on_batch_started(self):
        """批处理开始回调"""
        # 重置完成通知标志
        self._merge_completion_notified = False
        self._split_completion_notified = False
        
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.setText("取消批处理")
        self.progress_label.setText("批处理进行中...")
    
    def _on_batch_completed(self):
        """批处理完成回调"""
        print("[MainWindow] 收到批处理完成信号")
        
        # 判断当前标签页类型
        current_tab_index = self.tab_widget.currentIndex()
        
        if current_tab_index == 0:  # 合成标签页
            # 防重复机制：确保只处理一次合成完成信号
            if self._merge_completion_notified:
                print("[MainWindow] 合成完成通知已处理，忽略重复信号")
                return
            
            self._merge_completion_notified = True
            print("[MainWindow] 开始处理合成批处理完成")
            
            # 更新合成标签页
            if hasattr(self, 'simple_merge_tab'):
                self.simple_merge_tab.on_merge_completed()
                print("[MainWindow] 通知合成标签页完成")
        
        elif current_tab_index == 1:  # 分割标签页
            # 防重复机制：确保只处理一次分割完成信号
            if self._split_completion_notified:
                print("[MainWindow] 分割完成通知已处理，忽略重复信号")
                return
            
            self._split_completion_notified = True
            print("[MainWindow] 开始处理分割批处理完成")
            
            # 更新分割标签页
            if hasattr(self, 'simple_split_tab'):
                self.simple_split_tab.on_split_completed()
                print("[MainWindow] 通知分割标签页完成")
        
        elif current_tab_index == 2:  # 自动模式标签页
            # 自动模式有自己的完成处理逻辑，无需在这里处理
            print("[MainWindow] 自动模式标签页处理完成通知")
        
        self.reset_ui()
        
        # 增强的完成提示系统
        print("[MainWindow] 显示完成通知")
        self._show_completion_notification()
    
    def _show_completion_notification(self):
        """显示完成通知"""
        # 改进完成提示框，添加更详细的信息
        current_tab_index = self.tab_widget.currentIndex()
        
        # 获取处理统计信息
        stats = self.batch_processor.get_statistics()
        completed_count = stats.get('completed', 0)
        failed_count = stats.get('failed', 0)
        total_count = stats.get('total', 0)
        
        if current_tab_index == 0:  # 合成标签页
            title = "视频合成完成"
            message = f"🎉 视频合成批处理已完成！\n\n"
            message += f"✅ 成功处理：{completed_count} 个文件夹\n"
            if failed_count > 0:
                message += f"❌ 处理失败：{failed_count} 个文件夹\n"
            message += f"📁 总计：{total_count} 个文件夹\n\n"
            message += "请查看输出文件夹中的合成视频。"
        elif current_tab_index == 1:  # 分割标签页  
            title = "视频分割完成"
            message = f"🎉 视频分割批处理已完成！\n\n"
            message += f"✅ 成功处理：{completed_count} 个文件夹\n"
            if failed_count > 0:
                message += f"❌ 处理失败：{failed_count} 个文件夹\n"
            message += f"📁 总计：{total_count} 个文件夹\n\n"
            message += "请查看输出文件夹中的分割视频。"
        else:
            title = "批处理完成"
            message = f"🎉 所有文件夹处理完成！\n\n"
            message += f"✅ 成功：{completed_count} 个，❌ 失败：{failed_count} 个"
            
        # 显示完成对话框
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle(title)
        msg_box.setText(message)
        msg_box.setIcon(QMessageBox.Information)
        msg_box.setStandardButtons(QMessageBox.Ok)
        
        # 设置对话框始终显示在最前面
        msg_box.setWindowFlags(msg_box.windowFlags() | Qt.WindowStaysOnTopHint)
        msg_box.exec_()
    
    def _on_batch_paused(self):
        """批处理暂停回调"""
        self.progress_label.setText("批处理已暂停")
    
    def _on_batch_resumed(self):
        """批处理恢复回调"""
        self.progress_label.setText("批处理进行中...")
    
    def _on_batch_cancelled(self):
        """批处理取消回调"""
        self.progress_label.setText("批处理已取消")
        self.reset_ui()
    
    def _on_batch_overall_progress(self, progress):
        """批处理整体进度回调"""
        # 只更新简化标签页的进度，不更新主窗口进度条（已隐藏避免重复显示）
        if hasattr(self, 'simple_merge_tab'):
            self.simple_merge_tab.on_overall_progress(progress)
        if hasattr(self, 'simple_split_tab'):
            self.simple_split_tab.on_overall_progress(progress)
    
    def _setup_simple_merge_signals(self):
        """设置简化合成标签页的信号连接"""
        self.simple_merge_tab.start_merge_requested.connect(self._on_simple_merge_start)
        self.simple_merge_tab.pause_merge_requested.connect(self._on_simple_merge_pause)
        self.simple_merge_tab.resume_merge_requested.connect(self._on_simple_merge_resume)
        self.simple_merge_tab.cancel_merge_requested.connect(self._on_simple_merge_cancel)
        self.simple_merge_tab.config_changed.connect(self._on_config_changed)
    
    def _setup_simple_split_signals(self):
        """设置简化分割标签页的信号连接"""
        self.simple_split_tab.start_split_requested.connect(self._on_simple_split_start)
        self.simple_split_tab.pause_split_requested.connect(self._on_simple_split_pause)
        self.simple_split_tab.resume_split_requested.connect(self._on_simple_split_resume)
        self.simple_split_tab.cancel_split_requested.connect(self._on_simple_split_cancel)
    
    def _setup_auto_mode_signals(self):
        """设置自动模式标签页的信号连接"""
        self.auto_mode_tab.pipeline_started.connect(self._on_auto_mode_pipeline_started)
        self.auto_mode_tab.pipeline_stopped.connect(self._on_auto_mode_pipeline_stopped)
    
    def _on_unified_batch_start(self, process_type, settings):
        """统一批处理开始回调"""
        try:
            # 清空批处理器中的现有任务
            if hasattr(self.batch_processor, 'jobs'):
                self.batch_processor.jobs.clear()
            
            # 获取质量映射
            quality_map = {"高质量": "high", "中等质量": "medium", "快速编码": "low"}
            quality = quality_map.get(settings.get('quality', '高质量'), 'high')
            
            success_count = 0
            
            if process_type == "merge":
                # 添加合成任务
                for folder_info in settings['folders']:
                    folder_output = os.path.join(settings['output_folder'], folder_info.name)
                    os.makedirs(folder_output, exist_ok=True)
                    
                    # 使用UI传递的音频设置，而不是硬编码默认值
                    audio_settings = settings.get('audio_settings', {
                        'keep_original': True,
                        'original_volume': 100,
                        'replace_audio': False,
                        'replace_audio_path': '',
                        'replace_audio_is_folder': False,
                        'replace_volume': 100,
                        'background_audio': False,
                        'background_audio_path': '',
                        'background_audio_is_folder': False,
                        'background_volume': 50
                    })
                    
                    # 调试输出：显示实际使用的音频设置
                    print(f"[MainWindow] 文件夹 {folder_info.name} 使用音频设置: {audio_settings}")
                    
                    success = self.batch_processor.add_merge_job(
                        folder_info.path,
                        folder_output,
                        settings['videos_per_output'],
                        settings['total_outputs'],
                        settings['resolution'],
                        settings['bitrate'],
                        settings['reuse_material'],
                        audio_settings,
                        settings['use_gpu'],
                        quality
                    )
                    
                    if success:
                        success_count += 1
            
            elif process_type == "split":
                # 添加分割任务
                for folder_info in settings['folders']:
                    # 直接使用原文件夹名，不添加split_前缀
                    folder_output = os.path.join(settings['output_folder'], folder_info.name)
                    os.makedirs(folder_output, exist_ok=True)
                    
                    success = self.batch_processor.add_split_job(
                        folder_info.path,
                        folder_output,
                        settings['duration_range'],
                        settings['resolution'],
                        settings['bitrate'],
                        settings['use_gpu'],
                        quality,
                        settings['save_metadata'],
                        settings['delete_original']
                    )
                    
                    if success:
                        success_count += 1
            
            if success_count > 0:
                # 开始批处理
                self.batch_processor.start_batch()
            else:
                QMessageBox.warning(self, "启动失败", "没有成功添加任何处理任务")
                
        except Exception as e:
            QMessageBox.critical(self, "错误", f"启动批处理时发生错误：{str(e)}")
    
    def _on_unified_batch_pause(self):
        """统一批处理暂停回调"""
        self.batch_processor.pause_batch()
    
    def _on_unified_batch_resume(self):
        """统一批处理恢复回调"""
        self.batch_processor.resume_batch()
    
    def _on_unified_batch_cancel(self):
        """统一批处理取消回调"""
        self.batch_processor.cancel_batch()
    
    def _on_simple_merge_start(self, settings):
        """简化合成开始回调"""
        try:
            # 清空批处理器中的现有任务
            if hasattr(self.batch_processor, 'jobs'):
                self.batch_processor.jobs.clear()
            
            # 获取质量映射
            quality_map = {"高质量": "high", "中等质量": "medium", "快速编码": "low"}
            quality = quality_map.get(settings.get('quality', '高质量'), 'high')
            
            success_count = 0
            
            # 添加合成任务
            for folder_info in settings['folders']:
                folder_output = os.path.join(settings['output_folder'], folder_info.name)
                os.makedirs(folder_output, exist_ok=True)
                
                # 使用UI传递的音频设置
                audio_settings = settings.get('audio_settings', {
                    'keep_original': True,
                    'original_volume': 100,
                    'replace_audio': False,
                    'replace_audio_path': '',
                    'replace_audio_is_folder': False,
                    'replace_volume': 100,
                    'background_audio': False,
                    'background_audio_path': '',
                    'background_audio_is_folder': False,
                    'background_volume': 50
                })
                
                success = self.batch_processor.add_merge_job(
                    folder_info.path,
                    folder_output,
                    settings['videos_per_output'],
                    settings['total_outputs'],
                    settings['resolution'],
                    settings['bitrate'],
                    settings['reuse_material'],
                    audio_settings,
                    settings['use_gpu'],
                    quality
                )
                
                if success:
                    success_count += 1
            
            if success_count > 0:
                # 开始批处理
                self.batch_processor.start_batch()
                self.simple_merge_tab.on_merge_started()
            else:
                QMessageBox.warning(self, "启动失败", "没有成功添加任何处理任务")
                
        except Exception as e:
            QMessageBox.critical(self, "错误", f"启动合成批处理时发生错误：{str(e)}")
    
    def _on_simple_merge_pause(self):
        """简化合成暂停回调"""
        self.batch_processor.pause_batch()
        self.simple_merge_tab.on_merge_paused()
    
    def _on_simple_merge_resume(self):
        """简化合成恢复回调"""
        self.batch_processor.resume_batch()
        self.simple_merge_tab.on_merge_resumed()
    
    def _on_simple_merge_cancel(self):
        """简化合成取消回调"""
        self.batch_processor.cancel_batch()
        self.simple_merge_tab.on_merge_cancelled()
    
    def _on_simple_split_start(self, settings):
        """简化分割开始回调"""
        try:
            # 清空批处理器中的现有任务
            if hasattr(self.batch_processor, 'jobs'):
                self.batch_processor.jobs.clear()
            
            # 获取质量映射
            quality_map = {"高质量": "high", "中等质量": "medium", "快速编码": "low"}
            quality = quality_map.get(settings.get('quality', '中等质量'), 'medium')
            
            success_count = 0
            
            # 添加分割任务
            for folder_info in settings['folders']:
                # 直接使用原文件夹名，不添加split_前缀
                folder_output = os.path.join(settings['output_folder'], folder_info.name)
                os.makedirs(folder_output, exist_ok=True)
                
                success = self.batch_processor.add_split_job(
                    folder_info.path,
                    folder_output,
                    settings['duration_range'],
                    settings['resolution'],
                    settings['bitrate'],
                    True,  # 强制使用GPU
                    quality,
                    settings['save_metadata'],
                    settings['delete_original']
                )
                
                if success:
                    success_count += 1
            
            if success_count > 0:
                # 开始批处理
                self.batch_processor.start_batch()
                self.simple_split_tab.on_split_started()
            else:
                QMessageBox.warning(self, "启动失败", "没有成功添加任何处理任务")
                
        except Exception as e:
            QMessageBox.critical(self, "错误", f"启动分割批处理时发生错误：{str(e)}")
    
    def _on_simple_split_pause(self):
        """简化分割暂停回调"""
        self.batch_processor.pause_batch()
        self.simple_split_tab.on_split_paused()
    
    def _on_simple_split_resume(self):
        """简化分割恢复回调"""
        self.batch_processor.resume_batch()
        self.simple_split_tab.on_split_resumed()
    
    def _on_simple_split_cancel(self):
        """简化分割取消回调"""
        self.batch_processor.cancel_batch()
        self.simple_split_tab.on_split_cancelled()
    
    def _on_auto_mode_pipeline_started(self):
        """自动模式流水线启动回调"""
        # 这里可以添加全局状态更新，比如禁用其他标签页等
        print("[MainWindow] 自动模式流水线已启动")
    
    def _on_auto_mode_pipeline_stopped(self):
        """自动模式流水线停止回调"""
        # 这里可以添加全局状态更新，比如重新启用其他标签页等
        print("[MainWindow] 自动模式流水线已停止")
