"""
恢复对话框模块

提供任务恢复、失败重试、进度监控等UI功能
"""

import os
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                            QPushButton, QTableWidget, QTableWidgetItem,
                            QProgressBar, QTextEdit, QTabWidget, QWidget,
                            QGroupBox, QMessageBox, QHeaderView, QComboBox)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QFont, QColor

from core.task_manager import TaskManager, TaskStatus, FailureReason


class RecoveryDialog(QDialog):
    """任务恢复对话框"""
    
    # 信号定义
    job_selected = pyqtSignal(str)  # 选择恢复的任务ID
    retry_failed_tasks = pyqtSignal()
    cleanup_completed = pyqtSignal()
    
    def __init__(self, task_manager: TaskManager, parent=None):
        super().__init__(parent)
        self.task_manager = task_manager
        self.setWindowTitle("任务恢复管理")
        self.setModal(True)
        self.resize(800, 600)
        
        self.init_ui()
        self.load_data()
        
        # 定时刷新
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self.refresh_data)
        self.refresh_timer.start(2000)  # 每2秒刷新一次
    
    def init_ui(self):
        """初始化用户界面"""
        layout = QVBoxLayout()
        
        # 创建标签页
        self.tab_widget = QTabWidget()
        
        # 可恢复任务标签页
        self.resumable_tab = self.create_resumable_tab()
        self.tab_widget.addTab(self.resumable_tab, "可恢复任务")
        
        # 失败任务标签页
        self.failed_tab = self.create_failed_tab()
        self.tab_widget.addTab(self.failed_tab, "失败任务")
        
        # 统计信息标签页
        self.stats_tab = self.create_stats_tab()
        self.tab_widget.addTab(self.stats_tab, "统计信息")
        
        layout.addWidget(self.tab_widget)
        
        # 底部按钮
        button_layout = QHBoxLayout()
        
        self.resume_btn = QPushButton("恢复选中任务")
        self.resume_btn.clicked.connect(self.resume_selected_job)
        button_layout.addWidget(self.resume_btn)
        
        self.retry_btn = QPushButton("重试失败任务")
        self.retry_btn.clicked.connect(self.retry_failed_tasks.emit)
        button_layout.addWidget(self.retry_btn)
        
        self.cleanup_btn = QPushButton("清理完成任务")
        self.cleanup_btn.clicked.connect(self.cleanup_completed_jobs)
        button_layout.addWidget(self.cleanup_btn)
        
        button_layout.addStretch()
        
        self.close_btn = QPushButton("关闭")
        self.close_btn.clicked.connect(self.accept)
        button_layout.addWidget(self.close_btn)
        
        layout.addLayout(button_layout)
        
        self.setLayout(layout)
    
    def create_resumable_tab(self) -> QWidget:
        """创建可恢复任务标签页"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        # 说明文本
        info_label = QLabel("以下是可以恢复的未完成任务：")
        info_label.setFont(QFont("Arial", 10))
        layout.addWidget(info_label)
        
        # 任务表格
        self.resumable_table = QTableWidget()
        self.resumable_table.setColumnCount(7)
        self.resumable_table.setHorizontalHeaderLabels([
            "任务ID", "创建时间", "进度", "已完成", "失败", "状态", "操作"
        ])
        
        # 设置表格属性
        header = self.resumable_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeToContents)
        
        self.resumable_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.resumable_table.setAlternatingRowColors(True)
        
        layout.addWidget(self.resumable_table)
        
        widget.setLayout(layout)
        return widget
    
    def create_failed_tab(self) -> QWidget:
        """创建失败任务标签页"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        # 失败任务表格
        self.failed_table = QTableWidget()
        self.failed_table.setColumnCount(6)
        self.failed_table.setHorizontalHeaderLabels([
            "任务ID", "失败原因", "错误信息", "重试次数", "最后失败时间", "操作"
        ])
        
        # 设置表格属性
        header = self.failed_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        
        self.failed_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.failed_table.setAlternatingRowColors(True)
        
        layout.addWidget(self.failed_table)
        
        # 错误详情
        error_group = QGroupBox("错误详情")
        error_layout = QVBoxLayout()
        
        self.error_detail = QTextEdit()
        self.error_detail.setMaximumHeight(150)
        self.error_detail.setReadOnly(True)
        error_layout.addWidget(self.error_detail)
        
        error_group.setLayout(error_layout)
        layout.addWidget(error_group)
        
        # 连接选择事件
        self.failed_table.itemSelectionChanged.connect(self.on_failed_task_selected)
        
        widget.setLayout(layout)
        return widget
    
    def create_stats_tab(self) -> QWidget:
        """创建统计信息标签页"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        # 总体统计
        overall_group = QGroupBox("总体统计")
        overall_layout = QVBoxLayout()
        
        self.overall_stats = QLabel()
        self.overall_stats.setFont(QFont("Consolas", 10))
        self.overall_stats.setWordWrap(True)
        overall_layout.addWidget(self.overall_stats)
        
        overall_group.setLayout(overall_layout)
        layout.addWidget(overall_group)
        
        # 资源使用情况
        resource_group = QGroupBox("系统资源")
        resource_layout = QVBoxLayout()
        
        # 内存使用
        self.memory_label = QLabel("内存使用率:")
        resource_layout.addWidget(self.memory_label)
        self.memory_bar = QProgressBar()
        resource_layout.addWidget(self.memory_bar)
        
        # 磁盘使用
        self.disk_label = QLabel("磁盘使用率:")
        resource_layout.addWidget(self.disk_label)
        self.disk_bar = QProgressBar()
        resource_layout.addWidget(self.disk_bar)
        
        # CPU使用
        self.cpu_label = QLabel("CPU使用率:")
        resource_layout.addWidget(self.cpu_label)
        self.cpu_bar = QProgressBar()
        resource_layout.addWidget(self.cpu_bar)
        
        resource_group.setLayout(resource_layout)
        layout.addWidget(resource_group)
        
        layout.addStretch()
        
        widget.setLayout(layout)
        return widget
    
    def load_data(self):
        """加载数据"""
        self.load_resumable_jobs()
        self.load_failed_tasks()
        self.load_statistics()
    
    def refresh_data(self):
        """刷新数据"""
        self.load_data()
    
    def load_resumable_jobs(self):
        """加载可恢复的任务"""
        self.resumable_table.setRowCount(0)
        
        # 获取所有任务文件
        persistence_dir = self.task_manager.persistence_dir
        if not os.path.exists(persistence_dir):
            return
        
        job_files = [f for f in os.listdir(persistence_dir) 
                    if f.startswith('job_') and f.endswith('.json')]
        
        for job_file in job_files:
            job_id = job_file[:-5]  # 移除.json后缀
            
            # 尝试加载任务信息
            if self.task_manager.load_job(job_id):
                job_info = self.task_manager.current_job
                if job_info and job_info.status != TaskStatus.COMPLETED:
                    self._add_resumable_job_row(job_info)
    
    def _add_resumable_job_row(self, job_info):
        """添加可恢复任务行"""
        row = self.resumable_table.rowCount()
        self.resumable_table.insertRow(row)
        
        # 任务ID
        self.resumable_table.setItem(row, 0, QTableWidgetItem(job_info.job_id))
        
        # 创建时间
        create_time = job_info.created_time[:19].replace('T', ' ')  # 格式化时间
        self.resumable_table.setItem(row, 1, QTableWidgetItem(create_time))
        
        # 进度条
        progress_widget = QProgressBar()
        progress_widget.setValue(int(job_info.total_progress * 100))
        self.resumable_table.setCellWidget(row, 2, progress_widget)
        
        # 已完成数量
        self.resumable_table.setItem(row, 3, QTableWidgetItem(str(job_info.completed_tasks)))
        
        # 失败数量
        failed_item = QTableWidgetItem(str(job_info.failed_tasks))
        if job_info.failed_tasks > 0:
            failed_item.setBackground(QColor(255, 200, 200))
        self.resumable_table.setItem(row, 4, failed_item)
        
        # 状态
        status_item = QTableWidgetItem(job_info.status.value if hasattr(job_info.status, 'value') else str(job_info.status))
        self.resumable_table.setItem(row, 5, status_item)
        
        # 操作按钮
        resume_btn = QPushButton("恢复")
        resume_btn.clicked.connect(lambda: self.resume_job(job_info.job_id))
        self.resumable_table.setCellWidget(row, 6, resume_btn)
    
    def load_failed_tasks(self):
        """加载失败的任务"""
        self.failed_table.setRowCount(0)
        
        if not self.task_manager.current_job:
            return
        
        failed_tasks = self.task_manager.get_failed_tasks()
        
        for task in failed_tasks:
            self._add_failed_task_row(task)
    
    def _add_failed_task_row(self, task):
        """添加失败任务行"""
        row = self.failed_table.rowCount()
        self.failed_table.insertRow(row)
        
        # 任务ID
        self.failed_table.setItem(row, 0, QTableWidgetItem(task.task_id))
        
        # 失败原因
        reason = task.failure_reason.value if task.failure_reason else "未知"
        reason_item = QTableWidgetItem(reason)
        self.failed_table.setItem(row, 1, reason_item)
        
        # 错误信息（截断显示）
        error_msg = task.error_message[:50] + "..." if len(task.error_message) > 50 else task.error_message
        self.failed_table.setItem(row, 2, QTableWidgetItem(error_msg))
        
        # 重试次数
        retry_item = QTableWidgetItem(f"{task.retry_count}/{task.max_retries}")
        if task.retry_count >= task.max_retries:
            retry_item.setBackground(QColor(255, 200, 200))
        self.failed_table.setItem(row, 3, retry_item)
        
        # 最后失败时间
        # 这里简化处理，实际应该记录失败时间
        self.failed_table.setItem(row, 4, QTableWidgetItem("--"))
        
        # 操作按钮
        if task.retry_count < task.max_retries:
            retry_btn = QPushButton("重试")
            retry_btn.clicked.connect(lambda: self.retry_single_task(task.task_id))
            self.failed_table.setCellWidget(row, 5, retry_btn)
        else:
            skip_btn = QPushButton("跳过")
            skip_btn.setEnabled(False)
            self.failed_table.setCellWidget(row, 5, skip_btn)
    
    def load_statistics(self):
        """加载统计信息"""
        if self.task_manager.current_job:
            stats = self.task_manager.get_job_statistics()
            
            stats_text = f"""
总任务数: {stats.get('total_tasks', 0)}
已完成: {stats.get('completed', 0)}
失败: {stats.get('failed', 0)}
待处理: {stats.get('pending', 0)}
正在处理: {stats.get('running', 0)}
整体进度: {stats.get('overall_progress', 0.0):.1%}
预计剩余时间: {stats.get('estimated_remaining_time', 0):.1f} 秒
            """.strip()
            
            self.overall_stats.setText(stats_text)
        
        # 加载资源信息
        try:
            import psutil
            
            # 内存
            memory = psutil.virtual_memory()
            self.memory_label.setText(f"内存使用率: {memory.percent:.1f}%")
            self.memory_bar.setValue(int(memory.percent))
            
            # 磁盘
            disk = psutil.disk_usage('/')
            self.disk_label.setText(f"磁盘使用率: {disk.percent:.1f}%")
            self.disk_bar.setValue(int(disk.percent))
            
            # CPU
            cpu_percent = psutil.cpu_percent()
            self.cpu_label.setText(f"CPU使用率: {cpu_percent:.1f}%")
            self.cpu_bar.setValue(int(cpu_percent))
            
        except ImportError:
            self.memory_label.setText("内存使用率: 无法获取")
            self.disk_label.setText("磁盘使用率: 无法获取")
            self.cpu_label.setText("CPU使用率: 无法获取")
    
    def resume_selected_job(self):
        """恢复选中的任务"""
        current_row = self.resumable_table.currentRow()
        if current_row >= 0:
            job_id_item = self.resumable_table.item(current_row, 0)
            if job_id_item:
                job_id = job_id_item.text()
                self.job_selected.emit(job_id)
                self.accept()
    
    def resume_job(self, job_id: str):
        """恢复指定任务"""
        self.job_selected.emit(job_id)
        self.accept()
    
    def retry_single_task(self, task_id: str):
        """重试单个任务"""
        if task_id in self.task_manager.tasks:
            task = self.task_manager.tasks[task_id]
            if task.retry_count < task.max_retries:
                task.status = TaskStatus.PENDING
                task.error_message = ""
                self.task_manager.save_state()
                self.refresh_data()
    
    def cleanup_completed_jobs(self):
        """清理已完成的任务"""
        reply = QMessageBox.question(
            self, "确认清理", 
            "确定要清理所有已完成的任务记录吗？\n此操作不可撤销。",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.task_manager.cleanup_old_jobs(days=0)  # 清理所有已完成的
            self.cleanup_completed.emit()
            self.refresh_data()
    
    def on_failed_task_selected(self):
        """处理失败任务选择事件"""
        current_row = self.failed_table.currentRow()
        if current_row >= 0:
            task_id_item = self.failed_table.item(current_row, 0)
            if task_id_item and task_id_item.text() in self.task_manager.tasks:
                task = self.task_manager.tasks[task_id_item.text()]
                self.error_detail.setText(task.error_message)
    
    def closeEvent(self, event):
        """关闭事件处理"""
        self.refresh_timer.stop()
        event.accept()


class TaskProgressWidget(QWidget):
    """任务进度显示组件"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.task_manager = None
        self.init_ui()
        
        # 刷新定时器
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self.refresh_display)
        self.refresh_timer.start(1000)  # 每秒刷新
    
    def init_ui(self):
        """初始化界面"""
        layout = QVBoxLayout()
        
        # 当前任务信息
        self.current_task_label = QLabel("当前任务: 无")
        layout.addWidget(self.current_task_label)
        
        # 总体进度
        self.overall_progress = QProgressBar()
        layout.addWidget(self.overall_progress)
        
        # 详细信息
        self.detail_label = QLabel("等待开始...")
        self.detail_label.setFont(QFont("Consolas", 9))
        layout.addWidget(self.detail_label)
        
        self.setLayout(layout)
    
    def set_task_manager(self, task_manager: TaskManager):
        """设置任务管理器"""
        self.task_manager = task_manager
    
    def refresh_display(self):
        """刷新显示"""
        if not self.task_manager or not self.task_manager.current_job:
            return
        
        # 更新总体进度
        stats = self.task_manager.get_job_statistics()
        progress = int(stats.get('overall_progress', 0.0) * 100)
        self.overall_progress.setValue(progress)
        
        # 更新当前任务
        running_tasks = [t for t in self.task_manager.tasks.values() 
                        if t.status == TaskStatus.RUNNING]
        
        if running_tasks:
            current_task = running_tasks[0]
            self.current_task_label.setText(f"当前任务: {current_task.task_id}")
        else:
            self.current_task_label.setText("当前任务: 无")
        
        # 更新详细信息
        detail_text = f"""
已完成: {stats.get('completed', 0)} | 失败: {stats.get('failed', 0)} | 待处理: {stats.get('pending', 0)}
预计剩余: {stats.get('estimated_remaining_time', 0):.0f}秒
        """.strip()
        
        self.detail_label.setText(detail_text)
