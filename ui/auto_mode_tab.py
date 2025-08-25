"""
自动分割-合成模式UI标签页

提供统一的界面来配置和管理自动分割-合成流水线
"""

import os
import logging
from typing import List, Optional
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox,
    QLabel, QPushButton, QProgressBar, QTextEdit, QSpinBox, 
    QDoubleSpinBox, QComboBox, QCheckBox, QLineEdit, QFileDialog,
    QListWidget, QListWidgetItem, QSplitter, QFrame, QMessageBox,
    QTabWidget, QScrollArea
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtGui import QFont, QIcon, QPalette

from core.pipeline_controller import PipelineController
from core.pipeline_states import (
    PipelineState, PipelineConfig, create_default_config
)
from core.batch_processor import BatchProcessor


class AutoModeTab(QWidget):
    """自动分割-合成模式标签页"""
    
    # 信号定义
    folder_added = pyqtSignal(str)
    folder_removed = pyqtSignal(str)
    pipeline_started = pyqtSignal()
    pipeline_stopped = pyqtSignal()
    
    def __init__(self, batch_processor: BatchProcessor, parent=None):
        super().__init__(parent)
        
        # 核心组件
        self.batch_processor = batch_processor
        self.pipeline_controller = PipelineController(batch_processor, self)
        
        # 状态
        self.input_folders: List[str] = []
        self.current_config: Optional[PipelineConfig] = None
        
        # 日志
        self.logger = logging.getLogger(__name__)
        
        # 初始化UI
        self._init_ui()
        self._connect_signals()
        self._update_ui_state()
        
        # 状态更新定时器
        self.ui_update_timer = QTimer()
        self.ui_update_timer.timeout.connect(self._update_ui_state)
        self.ui_update_timer.setInterval(1000)  # 1秒更新一次
        self.ui_update_timer.start()
    
    def _init_ui(self):
        """初始化用户界面"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # 标题
        self._create_title_section(layout)
        
        # 主要内容区域
        main_splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(main_splitter)
        
        # 左侧：配置区域
        config_widget = self._create_config_section()
        main_splitter.addWidget(config_widget)
        
        # 右侧：进度和日志区域
        progress_widget = self._create_progress_section()
        main_splitter.addWidget(progress_widget)
        
        # 设置分割比例
        main_splitter.setSizes([400, 300])
        
        # 底部：控制按钮
        self._create_control_section(layout)
    
    def _create_title_section(self, layout):
        """创建标题区域"""
        title_frame = QFrame()
        title_frame.setFrameStyle(QFrame.StyledPanel)
        title_frame.setStyleSheet("""
            QFrame {
                background-color: #f0f0f0;
                border: 1px solid #d0d0d0;
                border-radius: 5px;
            }
        """)
        
        title_layout = QHBoxLayout(title_frame)
        
        # 标题文本
        title_label = QLabel("🔄 自动分割-合成模式")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_layout.addWidget(title_label)
        
        title_layout.addStretch()
        
        # 状态指示器
        self.status_label = QLabel("就绪")
        self.status_label.setStyleSheet("""
            QLabel {
                color: #666;
                font-weight: bold;
                padding: 5px 10px;
                border: 1px solid #ccc;
                border-radius: 3px;
                background-color: white;
            }
        """)
        title_layout.addWidget(self.status_label)
        
        layout.addWidget(title_frame)
    
    def _create_config_section(self) -> QWidget:
        """创建配置区域"""
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        
        config_widget = QWidget()
        layout = QVBoxLayout(config_widget)
        
        # 输入文件夹配置
        self._create_input_section(layout)
        
        # 输出配置
        self._create_output_section(layout)
        
        # 分割配置
        self._create_split_config_section(layout)
        
        # 合成配置
        self._create_merge_config_section(layout)
        
        # 高级配置
        self._create_advanced_config_section(layout)
        
        layout.addStretch()
        scroll_area.setWidget(config_widget)
        
        return scroll_area
    
    def _create_input_section(self, layout):
        """创建输入文件夹配置区域"""
        group = QGroupBox("📁 输入文件夹")
        group_layout = QVBoxLayout(group)
        
        # 文件夹列表
        self.input_folders_list = QListWidget()
        self.input_folders_list.setMaximumHeight(120)
        self.input_folders_list.setAcceptDrops(True)
        self.input_folders_list.setToolTip("拖拽文件夹到此处或使用按钮添加")
        group_layout.addWidget(self.input_folders_list)
        
        # 按钮区域
        buttons_layout = QHBoxLayout()
        
        self.add_folder_btn = QPushButton("添加文件夹")
        self.add_folder_btn.clicked.connect(self._add_input_folder)
        buttons_layout.addWidget(self.add_folder_btn)
        
        self.remove_folder_btn = QPushButton("移除选中")
        self.remove_folder_btn.clicked.connect(self._remove_input_folder)
        self.remove_folder_btn.setEnabled(False)
        buttons_layout.addWidget(self.remove_folder_btn)
        
        self.clear_folders_btn = QPushButton("清空列表")
        self.clear_folders_btn.clicked.connect(self._clear_input_folders)
        buttons_layout.addWidget(self.clear_folders_btn)
        
        buttons_layout.addStretch()
        group_layout.addLayout(buttons_layout)
        
        # 连接列表选择信号
        self.input_folders_list.itemSelectionChanged.connect(
            lambda: self.remove_folder_btn.setEnabled(
                len(self.input_folders_list.selectedItems()) > 0
            )
        )
        
        layout.addWidget(group)
    
    def _create_output_section(self, layout):
        """创建输出配置区域"""
        group = QGroupBox("📤 输出配置")
        group_layout = QGridLayout(group)
        
        # 分割输出文件夹
        group_layout.addWidget(QLabel("分割输出文件夹:"), 0, 0)
        self.split_output_edit = QLineEdit()
        self.split_output_edit.setPlaceholderText("选择分割文件的输出文件夹")
        group_layout.addWidget(self.split_output_edit, 0, 1)
        
        self.split_output_btn = QPushButton("浏览")
        self.split_output_btn.clicked.connect(
            lambda: self._browse_folder(self.split_output_edit)
        )
        group_layout.addWidget(self.split_output_btn, 0, 2)
        
        # 合成输出文件夹
        group_layout.addWidget(QLabel("合成输出文件夹:"), 1, 0)
        self.merge_output_edit = QLineEdit()
        self.merge_output_edit.setPlaceholderText("选择最终合成视频的输出文件夹")
        group_layout.addWidget(self.merge_output_edit, 1, 1)
        
        self.merge_output_btn = QPushButton("浏览")
        self.merge_output_btn.clicked.connect(
            lambda: self._browse_folder(self.merge_output_edit)
        )
        group_layout.addWidget(self.merge_output_btn, 1, 2)
        
        layout.addWidget(group)
    
    def _create_split_config_section(self, layout):
        """创建分割配置区域"""
        group = QGroupBox("✂️ 分割设置")
        group_layout = QGridLayout(group)
        
        # 分割时长范围
        group_layout.addWidget(QLabel("分割时长范围(秒):"), 0, 0)
        
        range_layout = QHBoxLayout()
        self.split_min_duration = QDoubleSpinBox()
        self.split_min_duration.setRange(0.5, 60.0)
        self.split_min_duration.setValue(2.0)
        self.split_min_duration.setSuffix(" 秒")
        range_layout.addWidget(self.split_min_duration)
        
        range_layout.addWidget(QLabel("到"))
        
        self.split_max_duration = QDoubleSpinBox()
        self.split_max_duration.setRange(0.5, 60.0)
        self.split_max_duration.setValue(4.0)
        self.split_max_duration.setSuffix(" 秒")
        range_layout.addWidget(self.split_max_duration)
        
        range_layout.addStretch()
        group_layout.addLayout(range_layout, 0, 1, 1, 2)
        
        # 分割质量
        group_layout.addWidget(QLabel("分割质量:"), 1, 0)
        self.split_quality = QComboBox()
        self.split_quality.addItems(["快速", "中等质量", "高质量"])
        self.split_quality.setCurrentText("中等质量")
        group_layout.addWidget(self.split_quality, 1, 1)
        
        # 删除原文件
        self.delete_original_cb = QCheckBox("分割完成后删除原文件")
        self.delete_original_cb.setToolTip("小心：此选项会永久删除原始视频文件")
        group_layout.addWidget(self.delete_original_cb, 2, 0, 1, 3)
        
        layout.addWidget(group)
    
    def _create_merge_config_section(self, layout):
        """创建合成配置区域"""
        group = QGroupBox("🎬 合成设置")
        group_layout = QGridLayout(group)
        
        # 每视频片段数
        group_layout.addWidget(QLabel("每视频片段数:"), 0, 0)
        self.clips_per_video = QSpinBox()
        self.clips_per_video.setRange(2, 20)
        self.clips_per_video.setValue(3)
        self.clips_per_video.setToolTip("每个合成视频包含的片段数量")
        group_layout.addWidget(self.clips_per_video, 0, 1)
        
        # 输出视频数量
        group_layout.addWidget(QLabel("输出视频数量:"), 1, 0)
        self.output_count = QSpinBox()
        self.output_count.setRange(1, 100)
        self.output_count.setValue(5)
        self.output_count.setToolTip("每个文件夹生成的合成视频数量")
        group_layout.addWidget(self.output_count, 1, 1)
        
        # 素材重复使用
        self.allow_reuse_cb = QCheckBox("允许素材重复使用")
        self.allow_reuse_cb.setChecked(True)
        self.allow_reuse_cb.setToolTip("允许同一片段在多个合成视频中出现")
        group_layout.addWidget(self.allow_reuse_cb, 2, 0, 1, 2)
        
        # 启用音频
        self.enable_audio_cb = QCheckBox("保留音频轨道")
        self.enable_audio_cb.setChecked(True)
        group_layout.addWidget(self.enable_audio_cb, 3, 0, 1, 2)
        
        layout.addWidget(group)
    
    def _create_advanced_config_section(self, layout):
        """创建高级配置区域"""
        group = QGroupBox("⚙️ 高级设置")
        group_layout = QGridLayout(group)
        
        # GPU加速
        self.use_gpu_cb = QCheckBox("启用GPU硬件加速")
        self.use_gpu_cb.setChecked(True)
        self.use_gpu_cb.setToolTip("使用显卡加速视频处理，提高处理速度")
        group_layout.addWidget(self.use_gpu_cb, 0, 0, 1, 2)
        
        # 分辨率设置
        group_layout.addWidget(QLabel("输出分辨率:"), 1, 0)
        self.resolution_combo = QComboBox()
        self.resolution_combo.addItems([
            "保持原始分辨率",
            "1920x1080 (1080p)",
            "1280x720 (720p)",
            "3840x2160 (4K)"
        ])
        group_layout.addWidget(self.resolution_combo, 1, 1)
        
        layout.addWidget(group)
    
    def _create_progress_section(self) -> QWidget:
        """创建进度和日志区域"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # 进度区域
        progress_group = QGroupBox("📊 处理进度")
        progress_layout = QVBoxLayout(progress_group)
        
        # 整体进度
        progress_layout.addWidget(QLabel("整体进度:"))
        self.overall_progress = QProgressBar()
        self.overall_progress.setRange(0, 100)
        self.overall_progress.setValue(0)
        self.overall_progress.setFormat("%p% - %v/%m")
        progress_layout.addWidget(self.overall_progress)
        
        # 阶段进度
        self.phase_label = QLabel("当前阶段: 待启动")
        progress_layout.addWidget(self.phase_label)
        
        self.phase_progress = QProgressBar()
        self.phase_progress.setRange(0, 100)
        self.phase_progress.setValue(0)
        progress_layout.addWidget(self.phase_progress)
        
        # 详细信息
        self.progress_details = QLabel("就绪")
        self.progress_details.setWordWrap(True)
        self.progress_details.setStyleSheet("""
            QLabel {
                padding: 5px;
                border: 1px solid #ddd;
                border-radius: 3px;
                background-color: #f9f9f9;
            }
        """)
        progress_layout.addWidget(self.progress_details)
        
        layout.addWidget(progress_group)
        
        # 日志区域
        log_group = QGroupBox("📝 处理日志")
        log_layout = QVBoxLayout(log_group)
        
        self.log_text = QTextEdit()
        self.log_text.setMaximumHeight(200)
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 9))
        log_layout.addWidget(self.log_text)
        
        # 清空日志按钮
        clear_log_btn = QPushButton("清空日志")
        clear_log_btn.clicked.connect(self.log_text.clear)
        log_layout.addWidget(clear_log_btn)
        
        layout.addWidget(log_group)
        
        return widget
    
    def _create_control_section(self, layout):
        """创建控制按钮区域"""
        control_frame = QFrame()
        control_frame.setFrameStyle(QFrame.StyledPanel)
        control_layout = QHBoxLayout(control_frame)
        
        # 主要控制按钮
        self.start_btn = QPushButton("🚀 开始自动处理")
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-weight: bold;
                padding: 10px 20px;
                border: none;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:disabled {
                background-color: #cccccc;
                color: #666666;
            }
        """)
        self.start_btn.clicked.connect(self._start_pipeline)
        control_layout.addWidget(self.start_btn)
        
        self.pause_btn = QPushButton("⏸️ 暂停")
        self.pause_btn.clicked.connect(self._pause_pipeline)
        self.pause_btn.setEnabled(False)
        control_layout.addWidget(self.pause_btn)
        
        self.stop_btn = QPushButton("⏹️ 停止")
        self.stop_btn.clicked.connect(self._stop_pipeline)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                padding: 10px 20px;
                border: none;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #da190b;
            }
            QPushButton:disabled {
                background-color: #cccccc;
                color: #666666;
            }
        """)
        control_layout.addWidget(self.stop_btn)
        
        control_layout.addStretch()
        
        # 重置按钮
        self.reset_btn = QPushButton("🔄 重置")
        self.reset_btn.clicked.connect(self._reset_pipeline)
        control_layout.addWidget(self.reset_btn)
        
        # 帮助按钮
        help_btn = QPushButton("❓ 帮助")
        help_btn.clicked.connect(self._show_help)
        control_layout.addWidget(help_btn)
        
        layout.addWidget(control_frame)
    
    def _connect_signals(self):
        """连接信号和槽"""
        # 流水线控制器信号
        self.pipeline_controller.state_changed.connect(self._on_state_changed)
        self.pipeline_controller.phase_progress.connect(self._on_phase_progress)
        self.pipeline_controller.overall_progress.connect(self._on_overall_progress)
        self.pipeline_controller.current_task_changed.connect(self._on_task_changed)
        self.pipeline_controller.pipeline_completed.connect(self._on_pipeline_completed)
        self.pipeline_controller.pipeline_failed.connect(self._on_pipeline_failed)
        
        # 验证输入
        self.split_min_duration.valueChanged.connect(self._validate_duration_range)
        self.split_max_duration.valueChanged.connect(self._validate_duration_range)
    
    def _add_input_folder(self):
        """添加输入文件夹"""
        folder = QFileDialog.getExistingDirectory(
            self, "选择输入文件夹", ""
        )
        if folder and folder not in self.input_folders:
            self.input_folders.append(folder)
            
            item = QListWidgetItem(folder)
            item.setToolTip(folder)
            self.input_folders_list.addItem(item)
            
            self.folder_added.emit(folder)
            self._log_message(f"添加输入文件夹: {folder}")
    
    def _remove_input_folder(self):
        """移除选中的输入文件夹"""
        current_item = self.input_folders_list.currentItem()
        if current_item:
            folder = current_item.text()
            if folder in self.input_folders:
                self.input_folders.remove(folder)
            
            row = self.input_folders_list.row(current_item)
            self.input_folders_list.takeItem(row)
            
            self.folder_removed.emit(folder)
            self._log_message(f"移除输入文件夹: {folder}")
    
    def _clear_input_folders(self):
        """清空输入文件夹列表"""
        self.input_folders.clear()
        self.input_folders_list.clear()
        self._log_message("清空输入文件夹列表")
    
    def _browse_folder(self, line_edit: QLineEdit):
        """浏览选择文件夹"""
        folder = QFileDialog.getExistingDirectory(
            self, "选择文件夹", line_edit.text()
        )
        if folder:
            line_edit.setText(folder)
    
    def _validate_duration_range(self):
        """验证分割时长范围"""
        min_val = self.split_min_duration.value()
        max_val = self.split_max_duration.value()
        
        if min_val >= max_val:
            # 自动调整
            if self.sender() == self.split_min_duration:
                self.split_max_duration.setValue(min_val + 0.5)
            else:
                self.split_min_duration.setValue(max_val - 0.5)
    
    def _create_config(self) -> PipelineConfig:
        """从UI创建配置对象"""
        config = create_default_config()
        
        # 输入输出配置
        config.input_folders = self.input_folders.copy()
        config.split_output_folder = self.split_output_edit.text().strip()
        config.merge_output_folder = self.merge_output_edit.text().strip()
        
        # 分割配置
        config.split_duration_range = (
            self.split_min_duration.value(),
            self.split_max_duration.value()
        )
        config.split_quality = self.split_quality.currentText()
        config.delete_original_after_split = self.delete_original_cb.isChecked()
        
        # 合成配置
        config.merge_clips_per_video = self.clips_per_video.value()
        config.merge_output_count = self.output_count.value()
        config.merge_allow_reuse = self.allow_reuse_cb.isChecked()
        config.merge_audio_enabled = self.enable_audio_cb.isChecked()
        
        # 高级配置
        config.use_gpu = self.use_gpu_cb.isChecked()
        
        # 分辨率处理
        resolution_text = self.resolution_combo.currentText()
        if "1920x1080" in resolution_text:
            config.split_resolution = "1920x1080"
            config.merge_resolution = "1920x1080"
        elif "1280x720" in resolution_text:
            config.split_resolution = "1280x720"
            config.merge_resolution = "1280x720"
        elif "3840x2160" in resolution_text:
            config.split_resolution = "3840x2160"
            config.merge_resolution = "3840x2160"
        else:
            config.split_resolution = None
            config.merge_resolution = None
        
        return config
    
    def _validate_config(self, config: PipelineConfig) -> tuple[bool, str]:
        """验证配置"""
        if not config.input_folders:
            return False, "请至少添加一个输入文件夹"
        
        if not config.split_output_folder:
            return False, "请选择分割输出文件夹"
        
        if not config.merge_output_folder:
            return False, "请选择合成输出文件夹"
        
        # 检查文件夹是否存在
        for folder in config.input_folders:
            if not os.path.exists(folder):
                return False, f"输入文件夹不存在: {folder}"
        
        return True, ""
    
    def _start_pipeline(self):
        """开始流水线处理"""
        try:
            # 创建配置
            config = self._create_config()
            
            # 验证配置
            is_valid, error_msg = self._validate_config(config)
            if not is_valid:
                QMessageBox.warning(self, "配置错误", error_msg)
                return
            
            # 保存当前配置
            self.current_config = config
            
            # 启动流水线
            success = self.pipeline_controller.start_pipeline(config)
            if success:
                self.pipeline_started.emit()
                self._log_message("自动分割-合成流水线启动成功")
            else:
                QMessageBox.critical(self, "启动失败", "无法启动自动处理流水线")
        
        except Exception as e:
            self.logger.error(f"启动流水线失败: {e}")
            QMessageBox.critical(self, "错误", f"启动失败: {str(e)}")
    
    def _pause_pipeline(self):
        """暂停流水线"""
        self.pipeline_controller.pause_pipeline()
        self._log_message("暂停处理")
    
    def _stop_pipeline(self):
        """停止流水线"""
        reply = QMessageBox.question(
            self, "确认停止", 
            "确定要停止当前的处理流程吗？\n未完成的任务将被取消。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.pipeline_controller.cancel_pipeline()
            self.pipeline_stopped.emit()
            self._log_message("用户停止了处理流程")
    
    def _reset_pipeline(self):
        """重置流水线"""
        self.pipeline_controller.reset()
        self.overall_progress.setValue(0)
        self.phase_progress.setValue(0)
        self.phase_label.setText("当前阶段: 待启动")
        self.progress_details.setText("就绪")
        self._log_message("重置处理流程")
    
    def _show_help(self):
        """显示帮助信息"""
        help_text = """
<h3>自动分割-合成模式使用说明</h3>

<h4>功能概述</h4>
<p>此模式可以自动完成视频的分割和合成处理，实现一键式的视频处理流水线。</p>

<h4>处理流程</h4>
<ol>
<li><b>分割阶段</b>：将输入文件夹中的视频按设定时长分割成小片段</li>
<li><b>合成阶段</b>：从分割片段中随机选择并合成新的视频</li>
</ol>

<h4>配置说明</h4>
<ul>
<li><b>输入文件夹</b>：包含待处理视频的文件夹</li>
<li><b>分割设置</b>：控制如何分割原视频</li>
<li><b>合成设置</b>：控制如何合成新视频</li>
<li><b>输出配置</b>：指定分割和合成文件的保存位置</li>
</ul>

<h4>注意事项</h4>
<ul>
<li>处理过程中请勿关闭程序</li>
<li>确保有足够的磁盘空间</li>
<li>建议在处理前备份原始文件</li>
</ul>
        """
        
        msg = QMessageBox(self)
        msg.setWindowTitle("帮助")
        msg.setText(help_text)
        msg.setTextFormat(Qt.RichText)
        msg.exec_()
    
    def _update_ui_state(self):
        """更新UI状态"""
        current_state = self.pipeline_controller.get_current_state()
        
        # 更新按钮状态
        if current_state == PipelineState.IDLE:
            self.start_btn.setEnabled(True)
            self.pause_btn.setEnabled(False)
            self.stop_btn.setEnabled(False)
            self.status_label.setText("就绪")
            self.status_label.setStyleSheet("""
                QLabel {
                    color: #666;
                    font-weight: bold;
                    padding: 5px 10px;
                    border: 1px solid #ccc;
                    border-radius: 3px;
                    background-color: white;
                }
            """)
        
        elif current_state in [PipelineState.SPLITTING, PipelineState.MERGING]:
            self.start_btn.setEnabled(False)
            self.pause_btn.setEnabled(True)
            self.stop_btn.setEnabled(True)
            self.status_label.setText("处理中")
            self.status_label.setStyleSheet("""
                QLabel {
                    color: white;
                    font-weight: bold;
                    padding: 5px 10px;
                    border: 1px solid #4CAF50;
                    border-radius: 3px;
                    background-color: #4CAF50;
                }
            """)
        
        elif current_state == PipelineState.PAUSED:
            self.start_btn.setEnabled(False)
            self.pause_btn.setText("▶️ 继续")
            self.pause_btn.clicked.disconnect()
            self.pause_btn.clicked.connect(self._resume_pipeline)
            self.stop_btn.setEnabled(True)
            self.status_label.setText("已暂停")
            self.status_label.setStyleSheet("""
                QLabel {
                    color: white;
                    font-weight: bold;
                    padding: 5px 10px;
                    border: 1px solid #FF9800;
                    border-radius: 3px;
                    background-color: #FF9800;
                }
            """)
        
        elif current_state == PipelineState.COMPLETED:
            self.start_btn.setEnabled(True)
            self.pause_btn.setEnabled(False)
            self.stop_btn.setEnabled(False)
            self.status_label.setText("已完成")
            self.status_label.setStyleSheet("""
                QLabel {
                    color: white;
                    font-weight: bold;
                    padding: 5px 10px;
                    border: 1px solid #4CAF50;
                    border-radius: 3px;
                    background-color: #4CAF50;
                }
            """)
        
        elif current_state == PipelineState.FAILED:
            self.start_btn.setEnabled(True)
            self.pause_btn.setEnabled(False)
            self.stop_btn.setEnabled(False)
            self.status_label.setText("失败")
            self.status_label.setStyleSheet("""
                QLabel {
                    color: white;
                    font-weight: bold;
                    padding: 5px 10px;
                    border: 1px solid #f44336;
                    border-radius: 3px;
                    background-color: #f44336;
                }
            """)
    
    def _resume_pipeline(self):
        """恢复流水线处理"""
        self.pipeline_controller.resume_pipeline()
        self.pause_btn.setText("⏸️ 暂停")
        self.pause_btn.clicked.disconnect()
        self.pause_btn.clicked.connect(self._pause_pipeline)
        self._log_message("恢复处理")
    
    def _on_state_changed(self, state_name: str):
        """处理状态变更"""
        self._log_message(f"状态变更: {state_name}")
    
    def _on_phase_progress(self, phase_name: str, progress: float):
        """处理阶段进度更新"""
        self.phase_label.setText(f"当前阶段: {phase_name}")
        self.phase_progress.setValue(int(progress * 100))
    
    def _on_overall_progress(self, progress: float):
        """处理整体进度更新"""
        self.overall_progress.setValue(int(progress * 100))
    
    def _on_task_changed(self, task: str):
        """处理当前任务变更"""
        self.progress_details.setText(task)
    
    def _on_pipeline_completed(self, result_message: str):
        """处理流水线完成"""
        self._log_message("=== 处理完成 ===")
        self._log_message(result_message)
        
        QMessageBox.information(
            self, "处理完成", 
            f"自动分割-合成处理已完成！\n\n{result_message}"
        )
    
    def _on_pipeline_failed(self, error_type: str, error_message: str):
        """处理流水线失败"""
        self._log_message(f"=== 处理失败 ===")
        self._log_message(f"{error_type}: {error_message}")
        
        QMessageBox.critical(
            self, "处理失败", 
            f"自动处理失败\n\n错误类型: {error_type}\n错误信息: {error_message}"
        )
    
    def _log_message(self, message: str):
        """添加日志消息"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] {message}"
        self.log_text.append(log_entry)
        
        # 自动滚动到底部
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        
        # 记录到日志系统
        self.logger.info(message)


# 导入datetime
from datetime import datetime
