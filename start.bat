@echo off
echo 启动视频合成软件...
echo.

REM 检查Python是否安装
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo 错误：未找到Python！
    echo 请先安装Python 3.8或更高版本
    pause
    exit /b 1
)

REM 检查依赖是否安装
echo 检查依赖...
python -c "import PyQt5" >nul 2>&1
if %errorlevel% neq 0 (
    echo 正在安装依赖...
    pip install -r requirements.txt
)

REM 启动应用程序
echo 启动应用程序...
python main.py

pause
