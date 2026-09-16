@echo off
chcp 65001 >nul
title Radar CNPJ RS - Parar
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Radar-AutoStart.ps1" -Parar
pause
