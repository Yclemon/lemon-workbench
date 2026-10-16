@echo off
chcp 65001 >nul
title 缺氧计算查询工具
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo   [错误] 没有找到 python
  echo.
  echo   请先安装 Python 3.8 或更高版本: https://www.python.org/downloads/
  echo   安装时记得勾选 "Add Python to PATH"
  echo.
  pause
  exit /b 1
)

echo.
echo   正在启动，浏览器会自动打开...
echo   用完直接关掉这个黑窗口即可。
echo.
python app.py
if errorlevel 1 (
  echo.
  echo   [错误] 启动失败，上面有具体原因。
  pause
)
