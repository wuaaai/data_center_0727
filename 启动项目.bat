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

set BACKEND_DIR=E:\Develop_docu\sql_0722_center\data_processing_center
set FRONTEND_DIR=E:\Develop_docu\sql_0722_center\data_processing_center\app

echo.
echo [1/2] 启动后端服务 (端口 8001)...
start "Backend-8001" cmd /c "cd /d %BACKEND_DIR% && title 后端API服务_8001 && .venv\Scripts\python.exe -u main.py"

echo [2/2] 启动前端 (端口 8000)...
start "Frontend-8000" cmd /c "cd /d %FRONTEND_DIR% && title 前端界面_8000 && npm run dev"

echo.
echo ============================================
echo   启动完成！
echo   前端: http://localhost:8000
echo   后端: http://localhost:8001
echo ============================================
echo.
echo 知识库管理、文档 CRUD、启用/禁用、元数据查看均已就绪。
echo 如需文档解析（上传 PDF/DOCX），请单独启动 MinerU 引擎：
echo   在 mineru_0720 目录下运行:
echo     .venv\Scripts\python.exe web_app\server.py
echo   或设置环境变量 PARSE_ENGINE=maas 使用内网引擎
echo.
echo 停止所有服务：双击"停止项目.bat"
echo.
pause
