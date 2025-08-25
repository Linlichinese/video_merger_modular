"""
简化的视频分割标签页

提供清爽的表格式多文件夹批处理界面，专注于分割功能
"""

import os
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
                            QComboBox, QGroupBox, QDoubleSpinBox, QCheckBox, QLineEdit, 
                            QTableWidget, QTableWidgetItem, QHeaderView, QFileDialog, 
                            QFrame, QProgressBar, QMessageBox)
from PyQt5.QtCore import Qt, pyqtSignal, QMimeData, QTimer
from PyQt5.QtGui import QColor, QDragEnterEvent, QDropEvent

from .batch_widgets import FolderInfo, FolderStatus


class SimpleSplitTab(QWidget):
    """简化的视频分割标签页"""
    
    # 信号定义
    start_split_requested = pyqtSignal(dict)  # 开始分割 (settings)
    pause_split_requested = pyqtSignal()
    resume_split_requested = pyqtSignal()
    cancel_split_requested = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.folder_list = []  # 文件夹列表
        self.batch_running = False
        self.batch_paused = False
        
        self.init_ui()
        self._setup_drag_drop()
    
    def init_ui(self):
        """初始化UI"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)
        
        # 标题
        title_label = QLabel("✂️ 视频分割 - 多文件夹批处理")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #FF5722; margin-bottom: 10px;")
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
            "☑", "序号", "文件夹名称", "视频数量", "分割模式", "进度", "状态"
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
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)  # 分割模式
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
        
        # 分割时长设置
        split_settings_layout = QHBoxLayout()
        split_settings_layout.addWidget(QLabel("最小时长:"))
        self.min_duration_spin = QDoubleSpinBox()
        self.min_duration_spin.setMinimum(0.1)
        self.min_duration_spin.setMaximum(3600.0)
        self.min_duration_spin.setValue(2.0)
        self.min_duration_spin.setDecimals(1)
        split_settings_layout.addWidget(self.min_duration_spin)
        split_settings_layout.addWidget(QLabel("秒"))
        
        split_settings_layout.addWidget(QLabel("   最大时长:"))
        self.max_duration_spin = QDoubleSpinBox()
        self.max_duration_spin.setMinimum(0.1)
        self.max_duration_spin.setMaximum(3600.0)
        self.max_duration_spin.setValue(4.0)
        self.max_duration_spin.setDecimals(1)
        split_settings_layout.addWidget(self.max_duration_spin)
        split_settings_layout.addWidget(QLabel("秒"))
        
        split_settings_layout.addStretch()
        output_layout.addLayout(split_settings_layout)
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
        self.resolution_combo.addItems(["保持原分辨率", "1920x1080", "1080x1920", "1280x720", "2560x1440", "3840x2160"])
        video_layout.addWidget(self.resolution_combo)
        
        video_layout.addWidget(QLabel("   码率:"))
        self.bitrate_edit = QLineEdit("5000k")
        self.bitrate_edit.setMaximumWidth(80)
        video_layout.addWidget(self.bitrate_edit)
        
        video_layout.addWidget(QLabel("   质量:"))
        self.quality_combo = QComboBox()
        self.quality_combo.addItems(["高质量", "中等质量", "快速编码"])
        self.quality_combo.setCurrentText("中等质量")
        video_layout.addWidget(self.quality_combo)
        
        video_layout.addStretch()
        video_group.setLayout(video_layout)
        second_row.addWidget(video_group)
        
        # 特殊设置
        special_group = QGroupBox("⚙️ 特殊设置")
        special_layout = QHBoxLayout()
        
        self.save_metadata_check = QCheckBox("保存元数据")
        self.save_metadata_check.setChecked(True)
        self.save_metadata_check.setToolTip("保存到segments_metadata.json文件，用于合成时避免同一原视频的片段出现在同一合成视频中")
        special_layout.addWidget(self.save_metadata_check)
        
        self.delete_original_check = QCheckBox("删除原文件")
        self.delete_original_check.setChecked(False)
        self.delete_original_check.setStyleSheet("color: #FF6B35;")
        self.delete_original_check.setToolTip("警告：删除原视频文件后无法恢复！")
        special_layout.addWidget(self.delete_original_check)
        
        special_layout.addStretch()
        special_group.setLayout(special_layout)
        second_row.addWidget(special_group)
        
        control_layout.addLayout(second_row)
        
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
        
        self.start_split_btn = QPushButton("▶️ 开始分割")
        self.start_split_btn.clicked.connect(self._start_split)
        self.start_split_btn.setMinimumHeight(40)
        self.start_split_btn.setStyleSheet("QPushButton { font-weight: bold; background-color: #FF5722; color: white; }")
        exec_layout.addWidget(self.start_split_btn)
        
        self.pause_resume_btn = QPushButton("⏸️ 暂停")
        self.pause_resume_btn.clicked.connect(self._pause_resume_split)
        self.pause_resume_btn.setEnabled(False)
        self.pause_resume_btn.setMinimumHeight(40)
        exec_layout.addWidget(self.pause_resume_btn)
        
        self.cancel_split_btn = QPushButton("❌ 取消")
        self.cancel_split_btn.clicked.connect(self._cancel_split)
        self.cancel_split_btn.setEnabled(False)
        self.cancel_split_btn.setMinimumHeight(40)
        exec_layout.addWidget(self.cancel_split_btn)
        
        exec_group.setLayout(exec_layout)
        third_row.addWidget(exec_group)
        
        # 整体进度
        progress_group = QGroupBox("📊 整体进度")
        progress_layout = QVBoxLayout()
        
        self.overall_progress_bar = QProgressBar()
        self.overall_progress_bar.setValue(0)
        progress_layout.addWidget(self.overall_progress_bar)
        
        self.progress_label = QLabel("准备就绪 - 请拖拽文件夹并配置设置")
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
        
        # 分割模式
        duration_text = f"{self.min_duration_spin.value():.1f}-{self.max_duration_spin.value():.1f}秒"
        self.folder_table.setItem(row, 4, QTableWidgetItem(duration_text))
        
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
            # 同时更新分割模式
            duration_text = f"{self.min_duration_spin.value():.1f}-{self.max_duration_spin.value():.1f}秒"
            self.folder_table.setItem(row, 4, QTableWidgetItem(duration_text))
    
    def _update_progress_text(self):
        """更新进度文本"""
        if not self.folder_list:
            self.progress_label.setText("准备就绪 - 请拖拽文件夹并配置设置")
        else:
            total_videos = sum(folder.video_count for folder in self.folder_list)
            self.progress_label.setText(f"已添加 {len(self.folder_list)} 个文件夹，共 {total_videos} 个视频，将按时长随机分割")
    
    def _start_split(self):
        """开始分割"""
        if not self._validate_settings():
            return
        
        # 收集设置
        settings = self._collect_settings()
        
        # 发射开始信号
        self.start_split_requested.emit(settings)
    
    def _pause_resume_split(self):
        """暂停/恢复分割"""
        if self.batch_paused:
            self.resume_split_requested.emit()
        else:
            self.pause_split_requested.emit()
    
    def _cancel_split(self):
        """取消分割"""
        reply = QMessageBox.question(
            self, "确认取消", 
            "确定要取消当前分割批处理吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.cancel_split_requested.emit()
    
    def _validate_settings(self) -> bool:
        """验证设置"""
        # 检查输出文件夹
        if not self.output_folder_edit.text():
            QMessageBox.warning(self, "设置错误", "请选择输出文件夹")
            return False
        
        # 检查文件夹列表
        if not self.folder_list:
            QMessageBox.warning(self, "设置错误", "请拖拽要处理的文件夹")
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
        
        # 检查时长设置
        min_duration = self.min_duration_spin.value()
        max_duration = self.max_duration_spin.value()
        
        if min_duration >= max_duration:
            QMessageBox.warning(self, "时长设置错误", "最小时长必须小于最大时长")
            return False
        
        # 检查删除原文件的确认
        if self.delete_original_check.isChecked():
            reply = QMessageBox.question(
                self, "确认删除原视频",
                "您选择了在分割完成后删除原视频文件。\n\n"
                "⚠️ 警告：此操作不可撤销！\n\n"
                "确定要继续吗？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply != QMessageBox.Yes:
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
        
        # 处理分辨率设置
        resolution = None
        if self.resolution_combo.currentText() != "保持原分辨率":
            resolution = self.resolution_combo.currentText()
        
        settings = {
            'output_folder': self.output_folder_edit.text(),
            'folders': selected_folders,
            'duration_range': (self.min_duration_spin.value(), self.max_duration_spin.value()),
            'resolution': resolution,
            'bitrate': self.bitrate_edit.text() if self.bitrate_edit.text() else None,
            'quality': self.quality_combo.currentText(),
            'save_metadata': self.save_metadata_check.isChecked(),
            'delete_original': self.delete_original_check.isChecked()
        }
        
        return settings
    
    # 批处理事件回调方法（由主窗口调用）
    def on_split_started(self):
        """分割开始回调"""
        self.batch_running = True
        self.start_split_btn.setEnabled(False)
        self.pause_resume_btn.setEnabled(True)
        self.cancel_split_btn.setEnabled(True)
        self.progress_label.setText("分割批处理进行中...")
    
    def on_split_completed(self):
        """分割完成回调"""
        self.batch_running = False
        self.start_split_btn.setEnabled(True)
        self.pause_resume_btn.setEnabled(False)
        self.cancel_split_btn.setEnabled(False)
        self.overall_progress_bar.setValue(100)
        self.progress_label.setText("🎉 分割批处理完成！")
        
        # 添加完成时的视觉反馈
        self._show_completion_animation()
        
        # 更新进度条样式为完成状态
        self.overall_progress_bar.setStyleSheet("""
            QProgressBar::chunk {
                background-color: #FF5722;
            }
            QProgressBar {
                border: 2px solid #FF5722;
                border-radius: 5px;
                text-align: center;
            }
        """)
    
    def on_split_paused(self):
        """分割暂停回调"""
        self.batch_paused = True
        self.pause_resume_btn.setText("▶️ 恢复")
        self.progress_label.setText("分割批处理已暂停")
    
    def on_split_resumed(self):
        """分割恢复回调"""
        self.batch_paused = False
        self.pause_resume_btn.setText("⏸️ 暂停")
        self.progress_label.setText("分割批处理进行中...")
    
    def on_split_cancelled(self):
        """分割取消回调"""
        self.batch_running = False
        self.batch_paused = False
        self.start_split_btn.setEnabled(True)
        self.pause_resume_btn.setEnabled(False)
        self.cancel_split_btn.setEnabled(False)
        self.progress_label.setText("分割批处理已取消")
    
    def on_overall_progress(self, progress):
        """整体进度更新回调"""
        progress_value = int(progress * 100)
        self.overall_progress_bar.setValue(progress_value)
        
        if self.batch_running:
            if progress < 1.0:
                # 显示更详细的进度信息
                selected_count = self._get_selected_folder_count()
                completed_count = len([f for f in self.folder_list if f.status == FolderStatus.COMPLETED])
                self.progress_label.setText(f"分割批处理进行中... {progress * 100:.1f}% (已完成 {completed_count}/{selected_count})")
            else:
                self.progress_label.setText("分割批处理完成！")
                # 添加完成时的视觉反馈
                self._show_completion_animation()
    
    def on_job_started(self, folder_path):
        """任务开始回调"""
        row = self._find_folder_row(folder_path)
        if row >= 0:
            # 更新状态
            status_item = QTableWidgetItem("分割中")
            status_item.setForeground(QColor("#FF5722"))
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
        # 分割持续时间设置
        self.min_duration_spin.setValue(config.get('split_min_duration', 2.0))
        self.max_duration_spin.setValue(config.get('split_max_duration', 4.0))
        
        # 输出设置
        # 如果配置中有保持原分辨率设置，转换为分辨率选择
        if config.get('split_keep_resolution', True):
            self.resolution_combo.setCurrentText("保持原分辨率")
        else:
            self.resolution_combo.setCurrentText(config.get('split_resolution', "1920x1080"))
        
        self.bitrate_edit.setText(config.get('split_bitrate', "5000k"))
        self.quality_combo.setCurrentText(config.get('split_quality', "中等质量"))
        self.save_metadata_check.setChecked(config.get('split_save_metadata', True))
        self.delete_original_check.setChecked(config.get('split_delete_original', False))
        
        # 输出文件夹（如果有的话）
        if hasattr(self, 'output_folder_edit'):
            self.output_folder_edit.setText(config.get('split_output_folder', ''))
    
    def get_config(self):
        """获取当前配置"""
        resolution_text = self.resolution_combo.currentText()
        keep_resolution = resolution_text == "保持原分辨率"
        
        config = {
            'split_min_duration': self.min_duration_spin.value(),
            'split_max_duration': self.max_duration_spin.value(),
            'split_keep_resolution': keep_resolution,
            'split_resolution': "1920x1080" if keep_resolution else resolution_text,
            'split_auto_bitrate': True,  # 简化版本默认自动码率
            'split_bitrate': self.bitrate_edit.text(),
            'split_quality': self.quality_combo.currentText(),
            'split_save_metadata': self.save_metadata_check.isChecked(),
            'split_delete_original': self.delete_original_check.isChecked(),
        }
        
        # 输出文件夹（如果有的话）
        if hasattr(self, 'output_folder_edit'):
            config['split_output_folder'] = self.output_folder_edit.text()
            
        return config
    
    def _show_completion_animation(self):
        """显示完成动画效果"""
        # 简单的闪烁效果
        original_style = self.progress_label.styleSheet()
        
        def flash_orange():
            self.progress_label.setStyleSheet("color: #FF5722; font-weight: bold; font-size: 14px;")
            QTimer.singleShot(500, lambda: self.progress_label.setStyleSheet(original_style))
        
        # 延迟执行闪烁效果
        QTimer.singleShot(100, flash_orange)
    
    def _get_selected_folder_count(self):
        """获取选中的文件夹数量"""
        selected_count = 0
        for row in range(self.folder_table.rowCount()):
            checkbox = self.folder_table.cellWidget(row, 0)
            if checkbox and checkbox.isChecked():
                selected_count += 1
        return selected_count

