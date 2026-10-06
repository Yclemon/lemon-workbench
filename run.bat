@echo off
chcp 65001 >nul
title Steam 游玩报告（本地）
cd /d "%~dp0"

set "PY="
where py >nul 2>nul && set "PY=py"
if not defined PY where python >nul 2>nul && set "PY=python"

if not defined PY (
  echo.
  echo   [x] 没有找到 Python
  echo       请先安装 Python 3.8 或更高版本: https://www.python.org/downloads/
  echo       安装时记得勾选 Add python.exe to PATH
  echo.
  pause
  exit /b 1
)

echo.
echo   Steam 游玩报告 —— 正在读取本机 Steam 数据...
echo   这个黑窗口不要关，关掉就等于退出程序。
echo.

%PY% app.py %*
set "RC=%ERRORLEVEL%"

echo.
if not "%RC%"=="0" echo   程序异常退出，代码 %RC%。
echo   程序已退出，按任意键关闭窗口。
pause
