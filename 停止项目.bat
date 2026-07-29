@echo off
chcp 65001 >nul
title 数据处理中心 - 停止

echo 正在停止所有服务...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000.*LISTENING') do taskkill /F /PID %%a 2>nul
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8001.*LISTENING') do taskkill /F /PID %%a 2>nul
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8003.*LISTENING') do taskkill /F /PID %%a 2>nul

echo.
echo 已停止所有服务（端口 8000/8001/8003）。
echo.
pause
