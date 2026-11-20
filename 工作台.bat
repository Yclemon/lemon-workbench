@echo off
chcp 936 >nul
setlocal enabledelayedexpansion
title 工作台 —— 我的自制小工具
cd /d "%~dp0"
set "ROOT=%~dp0"

:menu
cls
echo.
echo   ==========================================
echo      工 作 台
echo   ==========================================
echo.

set "SP_STATE=[ ] 未运行"
set "ONI_STATE=[ ] 未运行"
set "DIARY_STATE=[ ] 未运行"
netstat -ano 2>nul | findstr /R /C:"127.0.0.1:8770 .*LISTENING" >nul && set "SP_STATE=[*] 运行中"
netstat -ano 2>nul | findstr /R /C:"127.0.0.1:8781 .*LISTENING" >nul && set "ONI_STATE=[*] 运行中"
netstat -ano 2>nul | findstr /R /C:":8788 .*LISTENING" >nul && set "DIARY_STATE=[*] 运行中"

echo    ^| 1 ^| Steam 游玩报告        %SP_STATE%   端口 8770
echo    ^| 2 ^| 缺氧计算查询工具      %ONI_STATE%   端口 8781
echo.
echo    ^| 3 ^| 写日记  - 打开日记文件夹
echo    ^| 4 ^| 手机看日记            %DIARY_STATE%   端口 8788
echo    ^| 5 ^| 打开工作区文件夹
echo.
echo    ^| 0 ^| 退出
echo.
echo   ------------------------------------------
echo   选 1 / 2 / 4 会自动开浏览器
echo   用完关掉那个黑窗口就等于退出程序
echo   ------------------------------------------
echo.
set "CH="
set /p "CH=  请选择: "

if "%CH%"=="1" goto steam
if "%CH%"=="2" goto oni
if "%CH%"=="3" goto diary
if "%CH%"=="4" goto diarysrv
if "%CH%"=="5" goto folder
if "%CH%"=="0" exit /b 0
goto menu

:steam
cls
if exist "steam-play\app.py" (
  echo.
  echo   正在启动 Steam 游玩报告...
  echo.
  start "Steam 游玩报告" cmd /c "cd /d "%ROOT%steam-play" && python app.py"
  timeout /t 3 >nul
) else (
  echo.
  echo   [x] 找不到 steam-play\app.py
  pause
)
goto menu

:oni
cls
if exist "oni-tools\app.py" (
  echo.
  echo   正在启动 缺氧计算查询工具...
  echo.
  start "缺氧计算查询工具" cmd /c "cd /d "%ROOT%oni-tools" && python app.py"
  timeout /t 3 >nul
) else (
  echo.
  echo   [x] 找不到 oni-tools\app.py
  pause
)
goto menu

:diary
if not exist "diary" mkdir "diary"
start "" explorer "%ROOT%diary"
goto menu

:diarysrv
cls
if exist "diary_server.py" (
  echo.
  echo   正在启动 日记手机阅读服务...
  echo.
  echo   手机连同一个 WiFi，地址看新开那个窗口里打印的
  echo   （用 192.168 开头那个，其余是虚拟网卡）
  echo.
  start "日记手机阅读" /D "%ROOT:~0,-1%" python diary_server.py
  timeout /t 4 >nul
) else (
  echo.
  echo   [x] 找不到 diary_server.py
  pause
)
goto menu

:folder
start "" explorer "%ROOT%"
goto menu
