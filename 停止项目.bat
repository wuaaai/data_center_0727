@echo off
chcp 65001 >nul
title 数据处理中心 - 停止所有服务

echo 正在停止所有服务...

REM 杀掉所有占端口的进程
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000.*LISTENING') do taskkill /F /PID %%a 2>nul
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8001.*LISTENING') do taskkill /F /PID %%a 2>nul
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8003.*LISTENING') do taskkill /F /PID %%a 2>nul

echo 已停止所有服务

echo. & echo ============================================ & echo   启动项目.bat  - 启动所有服务 & echo   停止项目.bat  - 停止所有服务 & echo ============================================ & echo.

pause
