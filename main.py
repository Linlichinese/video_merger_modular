#!/usr/bin/env python3
"""
视频合成软件主入口

自动分割-合成模式集成版本
"""

import sys
import os
import logging
from PyQt5.QtWidgets import QApplication, QMessageBox
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from ui.main_window import VideoMergerApp
except ImportError as e:
    print(f"导入错误: {e}")
    print("请确保所有依赖已正确安装")
    sys.exit(1)


def setup_logging():
    """设置日志系统"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('video_merger.log', encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )


def check_dependencies():
    """检查必要的依赖"""
    # 模块包名和导入名的映射
    required_modules = {
        'PyQt5': 'PyQt5',
        'numpy': 'numpy',
        'opencv-python': 'cv2',
        'imageio-ffmpeg': 'imageio_ffmpeg',
        'Pillow': 'PIL',
        'psutil': 'psutil'
    }
    
    missing_modules = []
    for package_name, import_name in required_modules.items():
        try:
            __import__(import_name)
        except ImportError:
            missing_modules.append(package_name)
    
    if missing_modules:
        print("缺少以下依赖模块:")
        for module in missing_modules:
            print(f"  - {module}")
        print("\n请运行以下命令安装:")
        print(f"pip install {' '.join(missing_modules)}")
        return False
    
    return True


def main():
    """主函数"""
    # 设置日志
    setup_logging()
    logger = logging.getLogger(__name__)
    
    logger.info("启动视频合成软件...")
    
    # 检查依赖
    if not check_dependencies():
        input("按回车键退出...")
        sys.exit(1)
    
    # 创建应用程序
    app = QApplication(sys.argv)
    
    # 设置应用程序属性
    app.setApplicationName("视频合成软件")
    app.setApplicationVersion("2.2.0")
    app.setOrganizationName("VideoMerger")
    
    # 设置高DPI支持
    app.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    app.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    
    try:
        # 创建主窗口
        main_window = VideoMergerApp()
        main_window.show()
        
        logger.info("应用程序启动成功")
        
        # 显示欢迎消息
        QMessageBox.information(
            main_window,
            "欢迎使用",
            "🎉 视频合成软件已启动！\n\n"
            "新功能：自动分割-合成模式\n"
            "切换到 '🔄 自动模式' 标签页体验全新的自动化处理流程！"
        )
        
        # 运行应用程序
        sys.exit(app.exec_())
        
    except Exception as e:
        logger.error(f"应用程序运行错误: {e}")
        QMessageBox.critical(
            None,
            "错误",
            f"应用程序启动失败:\n{str(e)}\n\n请检查日志文件获取详细信息。"
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
