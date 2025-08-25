"""
简化的视频合成标签页

提供清爽的表格式多文件夹批处理界面，专注于合成功能
"""

import os
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
                            QComboBox, QGroupBox, QSpinBox, QCheckBox, QLineEdit, 
                            QTableWidget, QTableWidgetItem, QHeaderView, QFileDialog, 
                            QFrame, QProgressBar, QMessageBox, QSlider)
from PyQt5.QtCore import Qt, pyqtSignal, QMimeData, QTimer
from PyQt5.QtGui import QColor, QDragEnterEvent, QDropEvent

from .batch_widgets import FolderInfo, FolderStatus


class SimpleMergeTab(QWidget):
    """简化的视频合成标签页"""
    
    # 信号定义
    start_merge_requested = pyqtSignal(dict)  # 开始合成 (settings)
    pause_merge_requested = pyqtSignal()
    resume_merge_requested = pyqtSignal()
    cancel_merge_requested = pyqtSignal()
    config_changed = pyqtSignal()  # 配置发生变化
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.folder_list = []  # 文件夹列表
        self.batch_running = False
        self.batch_paused = False
        
        self.init_ui()
        self._setup_drag_drop()
        self._setup_config_change_signals()
    
    def init_ui(self):
        """初始化UI"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)
        
        # 标题
        title_label = QLabel("📹 视频合成 - 多文件夹批处理")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #2196F3; margin-bottom: 10px;")
        main_layout.addWidget(title_label)
        
        # 表格区域
        self._create_table_area(main_layout)
        
        # 控制面板
        self._create_control_panel(main_layout)
    
    def _create_table_area(self, main_layout):
        """创建表格区域"""
        # 表格组
        table_group = QGroupBox("📂 待处理文件夹列表 (请拖拽文件夹到此区域)")
        table_layout = QVBoxLayout()
        
        # 创建表格
        self.folder_table = QTableWidget()
        self.folder_table.setColumnCount(7)
        self.folder_table.setHorizontalHeaderLabels([
            "☑", "序号", "文件夹名称", "视频数量", "输出数量", "进度", "状态"
        ])
        
        # 设置表格属性
        self.folder_table.setAlternatingRowColors(True)
        self.folder_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.folder_table.verticalHeader().setVisible(False)
        self.folder_table.setAcceptDrops(True)
        self.folder_table.setDragDropMode(QTableWidget.DropOnly)
        
        # 连接双击事件
        self.folder_table.itemDoubleClicked.connect(self._on_folder_table_double_clicked)
        
        # 设置列宽
        header = self.folder_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)  # 复选框
        header.setSectionResizeMode(1, QHeaderView.Fixed)  # 序号
        header.setSectionResizeMode(2, QHeaderView.Stretch)  # 文件夹名称
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)  # 视频数量
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)  # 输出数量
        header.setSectionResizeMode(5, QHeaderView.Fixed)  # 进度
        header.setSectionResizeMode(6, QHeaderView.ResizeToContents)  # 状态
        
        # 设置固定列宽
        self.folder_table.setColumnWidth(0, 40)   # 复选框
        self.folder_table.setColumnWidth(1, 50)   # 序号
        self.folder_table.setColumnWidth(5, 120)  # 进度条
        
        # 设置最小高度
        self.folder_table.setMinimumHeight(250)
        
        table_layout.addWidget(self.folder_table)
        table_group.setLayout(table_layout)
        main_layout.addWidget(table_group)
    
    def _create_control_panel(self, main_layout):
        """创建控制面板"""
        control_frame = QFrame()
        control_frame.setFrameStyle(QFrame.StyledPanel)
        control_layout = QVBoxLayout(control_frame)
        control_layout.setContentsMargins(15, 15, 15, 15)
        control_layout.setSpacing(15)
        
        # 第一行：文件夹操作和输出设置
        first_row = QHBoxLayout()
        
        # 文件夹操作 - 只保留管理功能
        folder_ops_group = QGroupBox("📁 列表管理")
        folder_ops_layout = QHBoxLayout()
        
        self.remove_selected_btn = QPushButton("删除选中")
        self.remove_selected_btn.clicked.connect(self._remove_selected)
        folder_ops_layout.addWidget(self.remove_selected_btn)
        
        self.clear_all_btn = QPushButton("清空列表")
        self.clear_all_btn.clicked.connect(self._clear_all)
        folder_ops_layout.addWidget(self.clear_all_btn)
        
        folder_ops_group.setLayout(folder_ops_layout)
        first_row.addWidget(folder_ops_group)
        
        # 输出设置
        output_group = QGroupBox("📁 输出设置")
        output_layout = QVBoxLayout()
        
        # 输出文件夹
        output_folder_layout = QHBoxLayout()
        output_folder_layout.addWidget(QLabel("统一输出文件夹:"))
        self.output_folder_edit = QLineEdit()
        self.output_folder_edit.setReadOnly(True)
        output_folder_layout.addWidget(self.output_folder_edit, 1)
        self.output_browse_btn = QPushButton("浏览...")
        self.output_browse_btn.clicked.connect(self._browse_output_folder)
        output_folder_layout.addWidget(self.output_browse_btn)
        self.output_open_btn = QPushButton("打开文件夹")
        self.output_open_btn.clicked.connect(self._open_output_folder)
        output_folder_layout.addWidget(self.output_open_btn)
        output_layout.addLayout(output_folder_layout)
        
        # 输出数量设置
        output_settings_layout = QHBoxLayout()
        output_settings_layout.addWidget(QLabel("每个视频包含:"))
        self.videos_per_output_spin = QSpinBox()
        self.videos_per_output_spin.setMinimum(1)
        self.videos_per_output_spin.setValue(2)
        self.videos_per_output_spin.setMaximum(100)
        output_settings_layout.addWidget(self.videos_per_output_spin)
        output_settings_layout.addWidget(QLabel("个片段"))
        
        output_settings_layout.addWidget(QLabel("   总输出:"))
        self.total_outputs_spin = QSpinBox()
        self.total_outputs_spin.setMinimum(1)
        self.total_outputs_spin.setValue(1)
        self.total_outputs_spin.setMaximum(10000)
        output_settings_layout.addWidget(self.total_outputs_spin)
        output_settings_layout.addWidget(QLabel("个视频"))
        
        self.reuse_material_check = QCheckBox("重复使用素材")
        self.reuse_material_check.setChecked(True)
        output_settings_layout.addWidget(self.reuse_material_check)
        output_settings_layout.addStretch()
        
        output_layout.addLayout(output_settings_layout)
        output_group.setLayout(output_layout)
        first_row.addWidget(output_group, 1)
        
        control_layout.addLayout(first_row)
        
        # 第二行：编码设置
        second_row = QHBoxLayout()
        
        # 视频设置
        video_group = QGroupBox("🎥 视频设置")
        video_layout = QHBoxLayout()
        
        video_layout.addWidget(QLabel("分辨率:"))
        self.resolution_combo = QComboBox()
        self.resolution_combo.addItems(["1920x1080", "1080x1920", "1280x720", "2560x1440", "3840x2160"])
        video_layout.addWidget(self.resolution_combo)
        
        video_layout.addWidget(QLabel("   码率:"))
        self.bitrate_edit = QLineEdit("5000k")
        self.bitrate_edit.setMaximumWidth(80)
        video_layout.addWidget(self.bitrate_edit)
        
        video_layout.addWidget(QLabel("   质量:"))
        self.quality_combo = QComboBox()
        self.quality_combo.addItems(["高质量", "中等质量", "快速编码"])
        video_layout.addWidget(self.quality_combo)
        
        self.use_gpu_check = QCheckBox("GPU加速")
        self.use_gpu_check.setChecked(True)
        video_layout.addWidget(self.use_gpu_check)
        
        video_layout.addStretch()
        video_group.setLayout(video_layout)
        second_row.addWidget(video_group)
        
        control_layout.addLayout(second_row)
        
        # 音频设置行
        audio_row = QHBoxLayout()
        self._create_audio_settings(audio_row)
        control_layout.addLayout(audio_row)
        
        # 第三行：执行控制
        third_row = QHBoxLayout()
        
        # 批量选择
        select_group = QGroupBox("☑️ 批量选择")
        select_layout = QHBoxLayout()
        
        self.select_all_btn = QPushButton("全选")
        self.select_all_btn.clicked.connect(self._select_all)
        select_layout.addWidget(self.select_all_btn)
        
        self.select_none_btn = QPushButton("取消全选")
        self.select_none_btn.clicked.connect(self._select_none)
        select_layout.addWidget(self.select_none_btn)
        
        select_group.setLayout(select_layout)
        third_row.addWidget(select_group)
        
        # 执行控制
        exec_group = QGroupBox("🚀 执行控制")
        exec_layout = QHBoxLayout()
        
        self.start_merge_btn = QPushButton("▶️ 开始合成")
        self.start_merge_btn.clicked.connect(self._start_merge)
        self.start_merge_btn.setMinimumHeight(40)
        self.start_merge_btn.setStyleSheet("QPushButton { font-weight: bold; background-color: #4CAF50; color: white; }")
        exec_layout.addWidget(self.start_merge_btn)
        
        self.pause_resume_btn = QPushButton("⏸️ 暂停")
        self.pause_resume_btn.clicked.connect(self._pause_resume_merge)
        self.pause_resume_btn.setEnabled(False)
        self.pause_resume_btn.setMinimumHeight(40)
        exec_layout.addWidget(self.pause_resume_btn)
        
        self.cancel_merge_btn = QPushButton("❌ 取消")
        self.cancel_merge_btn.clicked.connect(self._cancel_merge)
        self.cancel_merge_btn.setEnabled(False)
        self.cancel_merge_btn.setMinimumHeight(40)
        exec_layout.addWidget(self.cancel_merge_btn)
        
        exec_group.setLayout(exec_layout)
        third_row.addWidget(exec_group)
        
        # 整体进度
        progress_group = QGroupBox("📊 整体进度")
        progress_layout = QVBoxLayout()
        
        self.overall_progress_bar = QProgressBar()
        self.overall_progress_bar.setValue(0)
        progress_layout.addWidget(self.overall_progress_bar)
        
        self.progress_label = QLabel("准备就绪 - 请添加文件夹并配置设置")
        self.progress_label.setAlignment(Qt.AlignCenter)
        self.progress_label.setStyleSheet("color: #666; font-size: 11px;")
        progress_layout.addWidget(self.progress_label)
        
        progress_group.setLayout(progress_layout)
        third_row.addWidget(progress_group)
        
        control_layout.addLayout(third_row)
        
        main_layout.addWidget(control_frame)
    
    def _setup_drag_drop(self):
        """设置拖拽功能"""
        self.setAcceptDrops(True)
        self.folder_table.setAcceptDrops(True)
    
    def dragEnterEvent(self, event: QDragEnterEvent):
        """拖拽进入事件"""
        if event.mimeData().hasUrls():
            # 检查是否包含文件夹
            urls = event.mimeData().urls()
            has_folder = any(url.isLocalFile() and os.path.isdir(url.toLocalFile()) for url in urls)
            if has_folder:
                event.acceptProposedAction()
                return
        event.ignore()
    
    def dropEvent(self, event: QDropEvent):
        """拖拽放下事件"""
        folders = []
        urls = event.mimeData().urls()
        
        for url in urls:
            if url.isLocalFile():
                path = url.toLocalFile()
                if os.path.isdir(path):
                    folders.append(path)
        
        if folders:
            self._add_folders_to_table(folders)
            event.acceptProposedAction()
    

    
    def _add_folders_to_table(self, folder_paths):
        """添加文件夹到表格"""
        added_count = 0
        for path in folder_paths:
            # 检查是否已存在
            if any(folder.path == path for folder in self.folder_list):
                continue
            
            try:
                folder_info = FolderInfo(path)
                if folder_info.video_count > 0:
                    self.folder_list.append(folder_info)
                    self._add_folder_to_table(folder_info)
                    added_count += 1
                else:
                    QMessageBox.warning(
                        self, "文件夹无效", 
                        f"文件夹 '{os.path.basename(path)}' 中没有找到视频文件，已跳过。"
                    )
            except Exception as e:
                QMessageBox.warning(
                    self, "添加失败", 
                    f"无法添加文件夹 '{os.path.basename(path)}'：{str(e)}"
                )
        
        if added_count > 0:
            self._update_table_numbers()
            self._update_progress_text()
    
    def _add_folder_to_table(self, folder_info: FolderInfo):
        """添加单个文件夹到表格"""
        row = self.folder_table.rowCount()
        self.folder_table.insertRow(row)
        
        # 复选框
        checkbox = QCheckBox()
        checkbox.setChecked(True)  # 默认选中
        self.folder_table.setCellWidget(row, 0, checkbox)
        
        # 序号
        self.folder_table.setItem(row, 1, QTableWidgetItem(str(row + 1)))
        
        # 文件夹名称
        self.folder_table.setItem(row, 2, QTableWidgetItem(folder_info.name))
        
        # 视频数量
        self.folder_table.setItem(row, 3, QTableWidgetItem(str(folder_info.video_count)))
        
        # 输出数量
        self.folder_table.setItem(row, 4, QTableWidgetItem(str(self.total_outputs_spin.value())))
        
        # 进度条
        progress_bar = QProgressBar()
        progress_bar.setValue(0)
        self.folder_table.setCellWidget(row, 5, progress_bar)
        
        # 状态
        status_item = QTableWidgetItem("待处理")
        status_item.setForeground(QColor("#666"))
        self.folder_table.setItem(row, 6, status_item)
    
    def _remove_selected(self):
        """删除选中的文件夹"""
        selected_rows = []
        for row in range(self.folder_table.rowCount()):
            checkbox = self.folder_table.cellWidget(row, 0)
            if checkbox and checkbox.isChecked():
                selected_rows.append(row)
        
        if not selected_rows:
            QMessageBox.warning(self, "未选中", "请先选择要删除的文件夹")
            return
        
        reply = QMessageBox.question(
            self, "确认删除", 
            f"确定要删除选中的 {len(selected_rows)} 个文件夹吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # 从后往前删除，避免索引错乱
            for row in sorted(selected_rows, reverse=True):
                self.folder_table.removeRow(row)
                if row < len(self.folder_list):
                    del self.folder_list[row]
            
            self._update_table_numbers()
            self._update_progress_text()
    
    def _clear_all(self):
        """清空所有文件夹"""
        if self.folder_table.rowCount() == 0:
            return
        
        reply = QMessageBox.question(
            self, "确认清空", 
            "确定要清空所有文件夹吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.folder_table.setRowCount(0)
            self.folder_list.clear()
            self._update_progress_text()
    
    def _select_all(self):
        """全选"""
        for row in range(self.folder_table.rowCount()):
            checkbox = self.folder_table.cellWidget(row, 0)
            if checkbox:
                checkbox.setChecked(True)
    
    def _select_none(self):
        """取消全选"""
        for row in range(self.folder_table.rowCount()):
            checkbox = self.folder_table.cellWidget(row, 0)
            if checkbox:
                checkbox.setChecked(False)
    
    def _browse_output_folder(self):
        """浏览选择输出文件夹"""
        folder = QFileDialog.getExistingDirectory(self, "选择统一输出文件夹")
        if folder:
            self.output_folder_edit.setText(folder)
    
    def _open_output_folder(self):
        """打开输出文件夹"""
        output_folder = self.output_folder_edit.text().strip()
        if not output_folder:
            QMessageBox.information(self, "提示", "请先选择输出文件夹")
            return
        
        if not os.path.exists(output_folder):
            QMessageBox.warning(self, "错误", f"输出文件夹不存在：\n{output_folder}")
            return
        
        try:
            import subprocess
            import platform
            
            if platform.system() == "Windows":
                os.startfile(output_folder)
            elif platform.system() == "Darwin":  # macOS
                subprocess.run(["open", output_folder])
            else:  # Linux
                subprocess.run(["xdg-open", output_folder])
        except Exception as e:
            QMessageBox.warning(self, "错误", f"无法打开文件夹：\n{str(e)}")
    
    def _on_folder_table_double_clicked(self, item):
        """处理文件夹表格双击事件"""
        if item is None:
            return
        
        row = item.row()
        if row < 0 or row >= len(self.folder_list):
            return
        
        folder_info = self.folder_list[row]
        folder_path = folder_info.path
        
        if not os.path.exists(folder_path):
            QMessageBox.warning(self, "错误", f"文件夹不存在：\n{folder_path}")
            return
        
        try:
            import subprocess
            import platform
            
            if platform.system() == "Windows":
                os.startfile(folder_path)
            elif platform.system() == "Darwin":  # macOS
                subprocess.run(["open", folder_path])
            else:  # Linux
                subprocess.run(["xdg-open", folder_path])
        except Exception as e:
            QMessageBox.warning(self, "错误", f"无法打开文件夹：\n{str(e)}")
    
    def _update_table_numbers(self):
        """更新表格序号"""
        for row in range(self.folder_table.rowCount()):
            self.folder_table.setItem(row, 1, QTableWidgetItem(str(row + 1)))
            # 同时更新输出数量
            self.folder_table.setItem(row, 4, QTableWidgetItem(str(self.total_outputs_spin.value())))
    
    def _update_progress_text(self):
        """更新进度文本"""
        if not self.folder_list:
            self.progress_label.setText("准备就绪 - 请添加文件夹并配置设置")
        else:
            total_videos = sum(folder.video_count for folder in self.folder_list)
            total_outputs = len(self.folder_list) * self.total_outputs_spin.value()
            self.progress_label.setText(f"已添加 {len(self.folder_list)} 个文件夹，共 {total_videos} 个视频，将生成 {total_outputs} 个合成视频")
    
    def _start_merge(self):
        """开始合成"""
        if not self._validate_settings():
            return
        
        # 收集设置
        settings = self._collect_settings()
        
        # 发射开始信号
        self.start_merge_requested.emit(settings)
    
    def _pause_resume_merge(self):
        """暂停/恢复合成"""
        if self.batch_paused:
            self.resume_merge_requested.emit()
        else:
            self.pause_merge_requested.emit()
    
    def _cancel_merge(self):
        """取消合成"""
        reply = QMessageBox.question(
            self, "确认取消", 
            "确定要取消当前合成批处理吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.cancel_merge_requested.emit()
    
    def _validate_settings(self) -> bool:
        """验证设置"""
        # 检查输出文件夹
        if not self.output_folder_edit.text():
            QMessageBox.warning(self, "设置错误", "请选择输出文件夹")
            return False
        
        # 检查文件夹列表
        if not self.folder_list:
            QMessageBox.warning(self, "设置错误", "请添加要处理的文件夹")
            return False
        
        # 检查是否有选中的文件夹
        selected_count = 0
        for row in range(self.folder_table.rowCount()):
            checkbox = self.folder_table.cellWidget(row, 0)
            if checkbox and checkbox.isChecked():
                selected_count += 1
        
        if selected_count == 0:
            QMessageBox.warning(self, "设置错误", "请至少选择一个文件夹进行处理")
            return False
        
        # 检查码率
        if not self.bitrate_edit.text():
            QMessageBox.warning(self, "设置错误", "请设置输出码率")
            return False
        
        # 验证音频设置
        audio_settings = self.get_audio_settings()
        if not self.validate_audio_settings(audio_settings):
            return False
        
        return True
    
    def _collect_settings(self) -> dict:
        """收集当前设置"""
        # 收集选中的文件夹
        selected_folders = []
        for row in range(self.folder_table.rowCount()):
            checkbox = self.folder_table.cellWidget(row, 0)
            if checkbox and checkbox.isChecked() and row < len(self.folder_list):
                selected_folders.append(self.folder_list[row])
        
        settings = {
            'output_folder': self.output_folder_edit.text(),
            'folders': selected_folders,
            'videos_per_output': self.videos_per_output_spin.value(),
            'total_outputs': self.total_outputs_spin.value(),
            'resolution': self.resolution_combo.currentText(),
            'bitrate': self.bitrate_edit.text(),
            'use_gpu': self.use_gpu_check.isChecked(),
            'quality': self.quality_combo.currentText(),
            'reuse_material': self.reuse_material_check.isChecked(),
            'audio_settings': self.get_audio_settings()
        }
        
        return settings
    
    # 批处理事件回调方法（由主窗口调用）
    def on_merge_started(self):
        """合成开始回调"""
        self.batch_running = True
        self.start_merge_btn.setEnabled(False)
        self.pause_resume_btn.setEnabled(True)
        self.cancel_merge_btn.setEnabled(True)
        self.progress_label.setText("合成批处理进行中...")
    
    def on_merge_completed(self):
        """合成完成回调"""
        self.batch_running = False
        self.start_merge_btn.setEnabled(True)
        self.pause_resume_btn.setEnabled(False)
        self.cancel_merge_btn.setEnabled(False)
        self.overall_progress_bar.setValue(100)
        self.progress_label.setText("🎉 合成批处理完成！")
        
        # 添加完成时的视觉反馈
        self._show_completion_animation()
        
        # 更新进度条样式为完成状态
        self.overall_progress_bar.setStyleSheet("""
            QProgressBar::chunk {
                background-color: #4CAF50;
            }
            QProgressBar {
                border: 2px solid #4CAF50;
                border-radius: 5px;
                text-align: center;
            }
        """)
    
    def on_merge_paused(self):
        """合成暂停回调"""
        self.batch_paused = True
        self.pause_resume_btn.setText("▶️ 恢复")
        self.progress_label.setText("合成批处理已暂停")
    
    def on_merge_resumed(self):
        """合成恢复回调"""
        self.batch_paused = False
        self.pause_resume_btn.setText("⏸️ 暂停")
        self.progress_label.setText("合成批处理进行中...")
    
    def on_merge_cancelled(self):
        """合成取消回调"""
        self.batch_running = False
        self.batch_paused = False
        self.start_merge_btn.setEnabled(True)
        self.pause_resume_btn.setEnabled(False)
        self.cancel_merge_btn.setEnabled(False)
        self.progress_label.setText("合成批处理已取消")
    
    def on_overall_progress(self, progress):
        """整体进度更新回调"""
        progress_value = int(progress * 100)
        self.overall_progress_bar.setValue(progress_value)
        
        if self.batch_running:
            if progress < 1.0:
                # 显示更详细的进度信息
                selected_count = self._get_selected_folder_count()
                completed_count = len([f for f in self.folder_list if f.status == FolderStatus.COMPLETED])
                self.progress_label.setText(f"合成批处理进行中... {progress * 100:.1f}% (已完成 {completed_count}/{selected_count})")
            else:
                self.progress_label.setText("合成批处理完成！")
                # 添加完成时的视觉反馈
                self._show_completion_animation()
    
    def on_job_started(self, folder_path):
        """任务开始回调"""
        row = self._find_folder_row(folder_path)
        if row >= 0:
            # 更新状态
            status_item = QTableWidgetItem("合成中")
            status_item.setForeground(QColor("#2196F3"))
            self.folder_table.setItem(row, 6, status_item)
    
    def on_job_progress(self, folder_path, progress):
        """任务进度回调"""
        row = self._find_folder_row(folder_path)
        if row >= 0:
            # 更新进度条
            progress_bar = self.folder_table.cellWidget(row, 5)
            if progress_bar:
                progress_bar.setValue(int(progress * 100))
    
    def on_job_completed(self, folder_path, message):
        """任务完成回调"""
        row = self._find_folder_row(folder_path)
        if row >= 0:
            # 更新状态
            status_item = QTableWidgetItem("已完成")
            status_item.setForeground(QColor("#4CAF50"))
            self.folder_table.setItem(row, 6, status_item)
            
            # 更新进度条
            progress_bar = self.folder_table.cellWidget(row, 5)
            if progress_bar:
                progress_bar.setValue(100)
    
    def on_job_failed(self, folder_path, error_message):
        """任务失败回调"""
        row = self._find_folder_row(folder_path)
        if row >= 0:
            # 更新状态
            status_item = QTableWidgetItem("失败")
            status_item.setForeground(QColor("#F44336"))
            self.folder_table.setItem(row, 6, status_item)
    
    def _find_folder_row(self, folder_path) -> int:
        """根据文件夹路径查找对应的表格行"""
        for i, folder_info in enumerate(self.folder_list):
            if folder_info.path == folder_path:
                return i
        return -1
    
    def load_config(self, config):
        """加载配置"""
        # 基本合成设置
        self.videos_per_output_spin.setValue(config.get('videos_per_output', 2))
        self.total_outputs_spin.setValue(config.get('total_outputs', 1))
        self.reuse_material_check.setChecked(config.get('reuse_material', True))
        
        # 输出设置
        self.resolution_combo.setCurrentText(config.get('resolution', "1920x1080"))
        self.bitrate_edit.setText(config.get('bitrate', "5000k"))
        self.quality_combo.setCurrentText(config.get('quality', "高质量"))
        self.use_gpu_check.setChecked(config.get('use_gpu', True))
        
        # 音频设置 - 恢复用户的音频配置
        print(f"[SimpleMergeTab] 加载音频配置: {config}")
        
        # 原音频设置
        self.keep_original_check.setChecked(config.get('keep_original', True))
        self.original_volume_slider.setValue(config.get('original_volume', 100))
        self.original_volume_label.setText(f"{config.get('original_volume', 100)}%")
        
        # 替换音频设置
        self.replace_audio_check.setChecked(config.get('replace_audio', False))
        self.replace_audio_edit.setText(config.get('replace_audio_path', ''))
        self.replace_volume_slider.setValue(config.get('replace_volume', 100))
        self.replace_volume_label.setText(f"{config.get('replace_volume', 100)}%")
        
        # 替换音频类型
        # 避免在加载配置时触发 on_replace_audio_type_changed 清空路径
        self.replace_audio_type_combo.blockSignals(True)
        if config.get('replace_audio_is_folder', False):
            self.replace_audio_type_combo.setCurrentText("选择文件夹")
        else:
            self.replace_audio_type_combo.setCurrentText("选择文件")
        self.replace_audio_type_combo.blockSignals(False)
        
        # 背景音设置
        self.background_audio_check.setChecked(config.get('background_audio', False))
        self.background_audio_edit.setText(config.get('background_audio_path', ''))
        self.background_volume_slider.setValue(config.get('background_volume', 50))
        self.background_volume_label.setText(f"{config.get('background_volume', 50)}%")
        
        # 背景音类型
        # 避免在加载配置时触发 on_background_audio_type_changed 清空路径
        self.background_audio_type_combo.blockSignals(True)
        if config.get('background_audio_is_folder', False):
            self.background_audio_type_combo.setCurrentText("选择文件夹")
        else:
            self.background_audio_type_combo.setCurrentText("选择文件")
        self.background_audio_type_combo.blockSignals(False)
        
        # 触发音频控件状态更新
        self.toggle_replace_audio(Qt.Checked if config.get('replace_audio', False) else Qt.Unchecked)
        self.toggle_background_audio(Qt.Checked if config.get('background_audio', False) else Qt.Unchecked)
        
        # 输出文件夹（如果有的话）
        if hasattr(self, 'output_folder_edit'):
            self.output_folder_edit.setText(config.get('output_folder', ''))
    
    def _setup_config_change_signals(self):
        """设置配置变化信号连接，实现音频设置的自动保存"""
        # 音频设置变化时发出配置变化信号
        self.keep_original_check.stateChanged.connect(self.config_changed.emit)
        self.original_volume_slider.valueChanged.connect(self.config_changed.emit)
        
        self.replace_audio_check.stateChanged.connect(self.config_changed.emit)
        self.replace_audio_edit.textChanged.connect(self.config_changed.emit)  # 添加音频路径变化信号
        self.replace_audio_type_combo.currentTextChanged.connect(self.config_changed.emit)
        self.replace_volume_slider.valueChanged.connect(self.config_changed.emit)
        
        self.background_audio_check.stateChanged.connect(self.config_changed.emit)
        self.background_audio_edit.textChanged.connect(self.config_changed.emit)  # 添加音频路径变化信号
        self.background_audio_type_combo.currentTextChanged.connect(self.config_changed.emit)
        self.background_volume_slider.valueChanged.connect(self.config_changed.emit)
        
        # 其他设置变化时也发出信号
        self.videos_per_output_spin.valueChanged.connect(self.config_changed.emit)
        self.total_outputs_spin.valueChanged.connect(self.config_changed.emit)
        self.reuse_material_check.stateChanged.connect(self.config_changed.emit)
        self.resolution_combo.currentTextChanged.connect(self.config_changed.emit)
        self.quality_combo.currentTextChanged.connect(self.config_changed.emit)
        self.use_gpu_check.stateChanged.connect(self.config_changed.emit)
        
        print("[SimpleMergeTab] 配置变化信号连接已设置")
    
    def get_config(self):
        """获取当前配置"""
        config = {
            'videos_per_output': self.videos_per_output_spin.value(),
            'total_outputs': self.total_outputs_spin.value(),
            'resolution': self.resolution_combo.currentText(),
            'bitrate': self.bitrate_edit.text(),
            'quality': self.quality_combo.currentText(),
            'use_gpu': self.use_gpu_check.isChecked(),
            'reuse_material': self.reuse_material_check.isChecked(),
            
            # 音频设置 - 保存用户的音频配置
            'keep_original': self.keep_original_check.isChecked(),
            'original_volume': self.original_volume_slider.value(),
            'replace_audio': self.replace_audio_check.isChecked(),
            'replace_audio_path': self.replace_audio_edit.text(),
            'replace_audio_is_folder': self.replace_audio_type_combo.currentText() == "选择文件夹",
            'replace_volume': self.replace_volume_slider.value(),
            'background_audio': self.background_audio_check.isChecked(),
            'background_audio_path': self.background_audio_edit.text(),
            'background_audio_is_folder': self.background_audio_type_combo.currentText() == "选择文件夹",
            'background_volume': self.background_volume_slider.value(),
        }
        
        print(f"[SimpleMergeTab] 保存音频配置: {config}")
        
        # 输出文件夹（如果有的话）
        if hasattr(self, 'output_folder_edit'):
            config['output_folder'] = self.output_folder_edit.text()
            
        return config
    
    def _show_completion_animation(self):
        """显示完成动画效果"""
        # 简单的闪烁效果
        original_style = self.progress_label.styleSheet()
        
        def flash_green():
            self.progress_label.setStyleSheet("color: #4CAF50; font-weight: bold; font-size: 14px;")
            QTimer.singleShot(500, lambda: self.progress_label.setStyleSheet(original_style))
        
        # 延迟执行闪烁效果
        QTimer.singleShot(100, flash_green)
    
    def _get_selected_folder_count(self):
        """获取选中的文件夹数量"""
        selected_count = 0
        for row in range(self.folder_table.rowCount()):
            checkbox = self.folder_table.cellWidget(row, 0)
            if checkbox and checkbox.isChecked():
                selected_count += 1
        return selected_count
    
    def _create_audio_settings(self, layout):
        """创建音频设置区域"""
        audio_group = QGroupBox("🎵 音频设置（替换音频和背景音会自动循环播放）")
        audio_layout = QVBoxLayout()
        
        # 原音频设置
        self._create_original_audio_settings(audio_layout)
        
        # 替换音频设置  
        self._create_replace_audio_settings(audio_layout)
        
        # 背景音设置
        self._create_background_audio_settings(audio_layout)
        
        audio_group.setLayout(audio_layout)
        layout.addWidget(audio_group)
    
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
        self.config_changed.emit()  # 发出配置变化信号
    
    def on_background_audio_type_changed(self):
        """背景音类型改变时清空路径"""
        self.background_audio_edit.setText("")
        self.config_changed.emit()  # 发出配置变化信号
    
    def browse_replace_audio(self):
        """浏览选择替换音频文件或文件夹"""
        if self.replace_audio_type_combo.currentText() == "选择文件":
            file, _ = QFileDialog.getOpenFileName(
                self, "选择替换音频文件", "", 
                "音频文件 (*.mp3 *.wav *.ogg *.flac *.m4a)"
            )
            if file:
                self.replace_audio_edit.setText(file)
                self.config_changed.emit()  # 发出配置变化信号
        else:  # 选择文件夹
            folder = QFileDialog.getExistingDirectory(self, "选择替换音频文件夹")
            if folder:
                self.replace_audio_edit.setText(folder)
                self.config_changed.emit()  # 发出配置变化信号
    
    def browse_background_audio(self):
        """浏览选择背景音文件或文件夹"""
        if self.background_audio_type_combo.currentText() == "选择文件":
            file, _ = QFileDialog.getOpenFileName(
                self, "选择背景音文件", "", 
                "音频文件 (*.mp3 *.wav *.ogg *.flac *.m4a)"
            )
            if file:
                self.background_audio_edit.setText(file)
                self.config_changed.emit()  # 发出配置变化信号
        else:  # 选择文件夹
            folder = QFileDialog.getExistingDirectory(self, "选择背景音文件夹")
            if folder:
                self.background_audio_edit.setText(folder)
                self.config_changed.emit()  # 发出配置变化信号
    
    def get_audio_settings(self):
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
    
    def validate_audio_settings(self, audio_settings):
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