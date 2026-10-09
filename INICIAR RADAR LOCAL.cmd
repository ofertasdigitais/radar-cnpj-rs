@echo off
chcp 65001 >nul
title Radar CNPJ RS - Local (sem Cloudflare)
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Radar-AutoStart.ps1"
if errorlevel 1 pause
