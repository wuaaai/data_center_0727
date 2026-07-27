@echo off
chcp 65001 >nul
title 数据处理中心 - 启动

echo ============================================
echo   数据处理中心 启动脚本
echo ============================================
echo.
echo   【重要】请先关闭所有已运行的服务，双击"停止项目.bat"
echo.
pause

set MINERU_DIR=E:\Develop_docu\sql_0722_center\mineru_0720
set BACKEND_DIR=E:\Develop_docu\sql_0722_center\data_processing_center
set FRONTEND_DIR=E:\Develop_docu\sql_0722_center\data_processing_center\app

echo.
echo [1/3] 启动 MinerU 模型服务 (端口 8003)...
start "MinerU-8003" cmd /c "cd /d %MINERU_DIR% && title MinerU模型服务_8003 && .venv\Scripts\python.exe -u web_app\server.py"
echo   等待模型预热（约 10 秒）...

echo [2/3] 启动后端服务 (端口 8001)...
start "Backend-8001" cmd /c "cd /d %BACKEND_DIR% && title 后端API服务_8001 && .venv\Scripts\python.exe -u main.py"

echo [3/3] 启动前端 (端口 8000)...
start "Frontend-8000" cmd /c "cd /d %FRONTEND_DIR% && title 前端界面_8000 && npm run dev"

echo.
echo ============================================
echo   启动完成！
echo   前端: http://localhost:8000
echo   后端: http://localhost:8001
echo   MinerU: http://localhost:8003
echo ============================================
echo.
echo 提示：等 MinerU 顶部状态栏绿点亮起后再上传文档（约10秒）
echo       停止所有服务：双击"停止项目.bat"
echo.
pause
