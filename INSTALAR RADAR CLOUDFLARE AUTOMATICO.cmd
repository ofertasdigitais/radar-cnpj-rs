@echo off
chcp 65001 >nul
title Radar CNPJ RS - Inicio automatico com Cloudflare
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Radar-AutoStart.ps1" -Instalar -ComCloudflare
if errorlevel 1 pause
