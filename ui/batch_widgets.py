"""
批处理UI组件模块

提供多文件夹选择、拖拽、进度展示等批处理相关的UI组件
"""

import os
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
                            QProgressBar, QFrame, QScrollArea, QFileDialog, QMessageBox,
                            QGroupBox, QListWidget, QListWidgetItem, QCheckBox, QComboBox)
from PyQt5.QtCore import Qt, pyqtSignal, QMimeData, QTimer
from PyQt5.QtGui import QPalette, QDragEnterEvent, QDropEvent, QFont, QPainter, QBrush
from enum import Enum
from typing import List, Dict, Optional


class BatchMode(Enum):
    """批处理模式"""
    SINGLE_FOLDER = "single"     # 单文件夹模式（兼容模式）
    MULTI_FOLDER = "multi"       # 多文件夹模式


class FolderStatus(Enum):
    """文件夹处理状态"""
    PENDING = "pending"          # 待处理
    PROCESSING = "processing"    # 处理中
    COMPLETED = "completed"      # 已完成
    FAILED = "failed"           # 失败
    PAUSED = "paused"           # 已暂停
    CANCELLED = "cancelled"      # 已取消


class FolderInfo:
    """文件夹信息类"""
    def __init__(self, path: str):
        self.path = path
        self.name = os.path.basename(path) or path
        self.status = FolderStatus.PENDING
        self.progress = 0.0
        self.error_message = ""
        self.video_count = 0
        self.start_time = None
        self.end_time = None
        
        # 扫描视频文件数量
        self._scan_video_files()
    
    def _scan_video_files(self):
        """扫描文件夹中的视频文件数量"""
        try:
            if os.path.isdir(self.path):
                video_extensions = ('.mp4', '.avi', '.mov', '.mkv', '.flv', '.wmv', '.mpeg', '.mpg')
                video_files = [f for f in os.listdir(self.path) 
                              if f.lower().endswith(video_extensions)]
                self.video_count = len(video_files)
        except Exception:
            self.video_count = 0


class FolderCard(QFrame):
    """文件夹卡片组件"""
    
    # 信号定义
    remove_requested = pyqtSignal(object)  # 请求移除文件夹
    pause_requested = pyqtSignal(object)   # 请求暂停处理
    resume_requested = pyqtSignal(object)  # 请求恢复处理
    
    def __init__(self, folder_info: FolderInfo, parent=None):
        super().__init__(parent)
        self.folder_info = folder_info
        self.init_ui()
        self.update_display()
    
    def init_ui(self):
        """初始化UI"""
        self.setFrameStyle(QFrame.StyledPanel)
        self.setLineWidth(1)
        self.setMinimumHeight(100)
        self.setMaximumHeight(120)
        
        # 主布局
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(5)
        
        # 顶部：文件夹名称和状态
        top_layout = QHBoxLayout()
        
        # 文件夹名称
        self.name_label = QLabel(self.folder_info.name)
        name_font = QFont()
        name_font.setBold(True)
        name_font.setPointSize(10)
        self.name_label.setFont(name_font)
        top_layout.addWidget(self.name_label, 1)
        
        # 状态标签
        self.status_label = QLabel("待处理")
        self.status_label.setAlignment(Qt.AlignRight)
        top_layout.addWidget(self.status_label)
        
        layout.addLayout(top_layout)
        
        # 中部：文件夹路径和视频数量
        middle_layout = QHBoxLayout()
        
        self.path_label = QLabel(self.folder_info.path)
        self.path_label.setStyleSheet("color: #666; font-size: 9pt;")
        self.path_label.setWordWrap(True)
        middle_layout.addWidget(self.path_label, 1)
        
        self.count_label = QLabel(f"{self.folder_info.video_count} 个视频")
        self.count_label.setStyleSheet("color: #666; font-size: 9pt;")
        self.count_label.setAlignment(Qt.AlignRight)
        middle_layout.addWidget(self.count_label)
        
        layout.addLayout(middle_layout)
        
        # 底部：进度条和控制按钮
        bottom_layout = QHBoxLayout()
        
        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        bottom_layout.addWidget(self.progress_bar, 1)
        
        # 控制按钮
        self.pause_resume_btn = QPushButton("暂停")
        self.pause_resume_btn.setMaximumWidth(60)
        self.pause_resume_btn.clicked.connect(self._on_pause_resume_clicked)
        self.pause_resume_btn.setEnabled(False)
        bottom_layout.addWidget(self.pause_resume_btn)
        
        self.remove_btn = QPushButton("移除")
        self.remove_btn.setMaximumWidth(60)
        self.remove_btn.clicked.connect(self._on_remove_clicked)
        bottom_layout.addWidget(self.remove_btn)
        
        layout.addLayout(bottom_layout)
    
    def update_display(self):
        """更新显示内容"""
        # 更新状态显示
        status_map = {
            FolderStatus.PENDING: ("待处理", "#666"),
            FolderStatus.PROCESSING: ("处理中", "#2196F3"),
            FolderStatus.COMPLETED: ("已完成", "#4CAF50"),
            FolderStatus.FAILED: ("失败", "#F44336"),
            FolderStatus.PAUSED: ("已暂停", "#FF9800"),
            FolderStatus.CANCELLED: ("已取消", "#9E9E9E")
        }
        
        status_text, status_color = status_map.get(self.folder_info.status, ("未知", "#666"))
        self.status_label.setText(status_text)
        self.status_label.setStyleSheet(f"color: {status_color}; font-weight: bold;")
        
        # 更新进度条
        progress_value = int(self.folder_info.progress * 100)
        self.progress_bar.setValue(progress_value)
        
        # 更新进度条颜色
        if self.folder_info.status == FolderStatus.COMPLETED:
            self.progress_bar.setStyleSheet("QProgressBar::chunk { background-color: #4CAF50; }")
        elif self.folder_info.status == FolderStatus.FAILED:
            self.progress_bar.setStyleSheet("QProgressBar::chunk { background-color: #F44336; }")
        elif self.folder_info.status == FolderStatus.PROCESSING:
            self.progress_bar.setStyleSheet("QProgressBar::chunk { background-color: #2196F3; }")
        elif self.folder_info.status == FolderStatus.PAUSED:
            self.progress_bar.setStyleSheet("QProgressBar::chunk { background-color: #FF9800; }")
        else:
            self.progress_bar.setStyleSheet("")
        
        # 更新按钮状态
        if self.folder_info.status == FolderStatus.PROCESSING:
            self.pause_resume_btn.setText("暂停")
            self.pause_resume_btn.setEnabled(True)
            self.remove_btn.setEnabled(False)
        elif self.folder_info.status == FolderStatus.PAUSED:
            self.pause_resume_btn.setText("恢复")
            self.pause_resume_btn.setEnabled(True)
            self.remove_btn.setEnabled(True)
        elif self.folder_info.status in [FolderStatus.COMPLETED, FolderStatus.FAILED, FolderStatus.CANCELLED]:
            self.pause_resume_btn.setEnabled(False)
            self.remove_btn.setEnabled(True)
        else:  # PENDING
            self.pause_resume_btn.setEnabled(False)
            self.remove_btn.setEnabled(True)
        
        # 更新卡片边框颜色
        if self.folder_info.status == FolderStatus.PROCESSING:
            self.setStyleSheet("FolderCard { border: 2px solid #2196F3; }")
        elif self.folder_info.status == FolderStatus.COMPLETED:
            self.setStyleSheet("FolderCard { border: 2px solid #4CAF50; }")
        elif self.folder_info.status == FolderStatus.FAILED:
            self.setStyleSheet("FolderCard { border: 2px solid #F44336; }")
        elif self.folder_info.status == FolderStatus.PAUSED:
            self.setStyleSheet("FolderCard { border: 2px solid #FF9800; }")
        else:
            self.setStyleSheet("FolderCard { border: 1px solid #ddd; }")
    
    def _on_pause_resume_clicked(self):
        """暂停/恢复按钮点击"""
        if self.folder_info.status == FolderStatus.PROCESSING:
            self.pause_requested.emit(self.folder_info)
        elif self.folder_info.status == FolderStatus.PAUSED:
            self.resume_requested.emit(self.folder_info)
    
    def _on_remove_clicked(self):
        """移除按钮点击"""
        reply = QMessageBox.question(
            self, "确认移除", 
            f"确定要从列表中移除文件夹 '{self.folder_info.name}' 吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.remove_requested.emit(self.folder_info)


class DropArea(QFrame):
    """拖拽区域组件"""
    
    folders_dropped = pyqtSignal(list)  # 文件夹被拖入信号
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()
        
    def init_ui(self):
        """初始化UI"""
        self.setAcceptDrops(True)
        self.setFrameStyle(QFrame.StyledPanel)
        self.setLineWidth(2)
        self.setMinimumHeight(100)
        
        # 设置虚线边框样式
        self.setStyleSheet("""
            DropArea {
                border: 2px dashed #ccc;
                border-radius: 10px;
                background-color: #f9f9f9;
            }
            DropArea:hover {
                border-color: #2196F3;
                background-color: #e3f2fd;
            }
        """)
        
        # 布局和标签
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        
        # 图标标签（使用文字代替图标）
        icon_label = QLabel("📁")
        icon_label.setAlignment(Qt.AlignCenter)
        icon_label.setStyleSheet("font-size: 32px;")
        layout.addWidget(icon_label)
        
        # 主要提示文字
        main_label = QLabel("拖拽文件夹到此处")
        main_label.setAlignment(Qt.AlignCenter)
        main_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #333;")
        layout.addWidget(main_label)
        
        # 次要提示文字
        sub_label = QLabel("或点击下方按钮选择文件夹")
        sub_label.setAlignment(Qt.AlignCenter)
        sub_label.setStyleSheet("font-size: 11px; color: #666;")
        layout.addWidget(sub_label)
    
    def dragEnterEvent(self, event: QDragEnterEvent):
        """拖拽进入事件"""
        if event.mimeData().hasUrls():
            # 检查是否包含文件夹
            urls = event.mimeData().urls()
            has_folder = any(url.isLocalFile() and os.path.isdir(url.toLocalFile()) for url in urls)
            if has_folder:
                event.acceptProposedAction()
                self.setStyleSheet("""
                    DropArea {
                        border: 2px dashed #2196F3;
                        border-radius: 10px;
                        background-color: #e3f2fd;
                    }
                """)
                return
        event.ignore()
    
    def dragLeaveEvent(self, event):
        """拖拽离开事件"""
        self.setStyleSheet("""
            DropArea {
                border: 2px dashed #ccc;
                border-radius: 10px;
                background-color: #f9f9f9;
            }
            DropArea:hover {
                border-color: #2196F3;
                background-color: #e3f2fd;
            }
        """)
    
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
            self.folders_dropped.emit(folders)
            event.acceptProposedAction()
        
        # 恢复样式
        self.dragLeaveEvent(event)


class MultiFolderManager(QWidget):
    """多文件夹管理组件"""
    
    # 信号定义
    folders_changed = pyqtSignal(list)      # 文件夹列表变化
    batch_start_requested = pyqtSignal()    # 请求开始批处理
    batch_pause_requested = pyqtSignal()    # 请求暂停批处理
    batch_resume_requested = pyqtSignal()   # 请求恢复批处理
    batch_cancel_requested = pyqtSignal()   # 请求取消批处理
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.folders: List[FolderInfo] = []
        self.folder_cards: Dict[str, FolderCard] = {}  # path -> FolderCard
        self.batch_running = False
        self.batch_paused = False
        
        self.init_ui()
    
    def init_ui(self):
        """初始化UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        
        # 拖拽区域
        self.drop_area = DropArea()
        self.drop_area.folders_dropped.connect(self.add_folders)
        layout.addWidget(self.drop_area)
        
        # 按钮区域
        buttons_layout = QHBoxLayout()
        
        self.add_folder_btn = QPushButton("添加文件夹")
        self.add_folder_btn.clicked.connect(self.browse_add_folder)
        buttons_layout.addWidget(self.add_folder_btn)
        
        self.add_multiple_btn = QPushButton("批量添加文件夹")
        self.add_multiple_btn.clicked.connect(self.browse_add_multiple_folders)
        buttons_layout.addWidget(self.add_multiple_btn)
        
        self.clear_all_btn = QPushButton("清空列表")
        self.clear_all_btn.clicked.connect(self.clear_all_folders)
        buttons_layout.addWidget(self.clear_all_btn)
        
        buttons_layout.addStretch()
        layout.addLayout(buttons_layout)
        
        # 文件夹列表滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setMinimumHeight(200)
        
        # 文件夹列表容器
        self.folders_container = QWidget()
        self.folders_layout = QVBoxLayout(self.folders_container)
        self.folders_layout.setContentsMargins(5, 5, 5, 5)
        self.folders_layout.setSpacing(5)
        self.folders_layout.addStretch()  # 底部弹簧
        
        scroll_area.setWidget(self.folders_container)
        layout.addWidget(scroll_area)
        
        # 统计信息
        self.stats_label = QLabel("文件夹数量: 0")
        self.stats_label.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(self.stats_label)
    
    def add_folders(self, folder_paths: List[str]):
        """添加文件夹到列表"""
        added_count = 0
        for path in folder_paths:
            if not self._folder_exists(path):
                try:
                    folder_info = FolderInfo(path)
                    if folder_info.video_count > 0:  # 只添加包含视频文件的文件夹
                        self.folders.append(folder_info)
                        self._create_folder_card(folder_info)
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
            self._update_stats()
            self.folders_changed.emit(self.folders.copy())
            
            if added_count < len(folder_paths):
                skipped = len(folder_paths) - added_count
                QMessageBox.information(
                    self, "添加完成", 
                    f"成功添加 {added_count} 个文件夹，跳过 {skipped} 个无效文件夹。"
                )
    
    def browse_add_folder(self):
        """浏览添加单个文件夹"""
        folder = QFileDialog.getExistingDirectory(self, "选择要添加的文件夹")
        if folder:
            self.add_folders([folder])
    
    def browse_add_multiple_folders(self):
        """浏览添加多个文件夹"""
        # PyQt5不直接支持多选文件夹，所以提示用户使用拖拽
        QMessageBox.information(
            self, "批量添加文件夹", 
            "请使用拖拽方式批量添加文件夹：\n\n"
            "1. 打开文件资源管理器\n"
            "2. 选择多个文件夹（Ctrl+点击）\n"
            "3. 拖拽到上方的拖拽区域"
        )
    
    def clear_all_folders(self):
        """清空所有文件夹"""
        if not self.folders:
            return
            
        reply = QMessageBox.question(
            self, "确认清空", 
            "确定要清空所有文件夹吗？正在处理的任务将被取消。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # 先取消所有正在进行的任务
            if self.batch_running:
                self.batch_cancel_requested.emit()
            
            # 清空UI
            for card in self.folder_cards.values():
                card.setParent(None)
                card.deleteLater()
            
            # 清空数据
            self.folders.clear()
            self.folder_cards.clear()
            self.batch_running = False
            self.batch_paused = False
            
            self._update_stats()
            self.folders_changed.emit([])
    
    def remove_folder(self, folder_info: FolderInfo):
        """移除指定文件夹"""
        if folder_info in self.folders:
            # 移除UI
            card = self.folder_cards.get(folder_info.path)
            if card:
                card.setParent(None)
                card.deleteLater()
                del self.folder_cards[folder_info.path]
            
            # 移除数据
            self.folders.remove(folder_info)
            
            self._update_stats()
            self.folders_changed.emit(self.folders.copy())
    
    def update_folder_progress(self, folder_path: str, progress: float, status: FolderStatus = None):
        """更新文件夹进度"""
        folder_info = self._find_folder_by_path(folder_path)
        if folder_info:
            folder_info.progress = progress
            if status:
                folder_info.status = status
            
            card = self.folder_cards.get(folder_path)
            if card:
                card.update_display()
    
    def get_pending_folders(self) -> List[FolderInfo]:
        """获取待处理的文件夹列表"""
        return [f for f in self.folders if f.status == FolderStatus.PENDING]
    
    def get_processing_folders(self) -> List[FolderInfo]:
        """获取正在处理的文件夹列表"""
        return [f for f in self.folders if f.status == FolderStatus.PROCESSING]
    
    def _folder_exists(self, path: str) -> bool:
        """检查文件夹是否已存在"""
        return any(f.path == path for f in self.folders)
    
    def _find_folder_by_path(self, path: str) -> Optional[FolderInfo]:
        """根据路径查找文件夹信息"""
        for folder in self.folders:
            if folder.path == path:
                return folder
        return None
    
    def _create_folder_card(self, folder_info: FolderInfo):
        """创建文件夹卡片"""
        card = FolderCard(folder_info)
        card.remove_requested.connect(self.remove_folder)
        card.pause_requested.connect(self._on_folder_pause_requested)
        card.resume_requested.connect(self._on_folder_resume_requested)
        
        # 插入到布局中（在弹簧之前）
        self.folders_layout.insertWidget(self.folders_layout.count() - 1, card)
        self.folder_cards[folder_info.path] = card
    
    def _update_stats(self):
        """更新统计信息"""
        total = len(self.folders)
        pending = len([f for f in self.folders if f.status == FolderStatus.PENDING])
        processing = len([f for f in self.folders if f.status == FolderStatus.PROCESSING])
        completed = len([f for f in self.folders if f.status == FolderStatus.COMPLETED])
        failed = len([f for f in self.folders if f.status == FolderStatus.FAILED])
        
        stats_text = f"文件夹数量: {total}"
        if total > 0:
            stats_text += f" (待处理: {pending}, 处理中: {processing}, 已完成: {completed}"
            if failed > 0:
                stats_text += f", 失败: {failed}"
            stats_text += ")"
        
        self.stats_label.setText(stats_text)
    
    def _on_folder_pause_requested(self, folder_info: FolderInfo):
        """文件夹暂停请求"""
        # 这里需要与批处理管理器通信，暂停特定文件夹的处理
        # 具体实现将在批处理管理器中完成
        pass
    
    def _on_folder_resume_requested(self, folder_info: FolderInfo):
        """文件夹恢复请求"""
        # 这里需要与批处理管理器通信，恢复特定文件夹的处理
        # 具体实现将在批处理管理器中完成
        pass




