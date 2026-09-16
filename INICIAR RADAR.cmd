@echo off
chcp 65001 >nul
title Radar CNPJ RS
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Iniciar-Radar.ps1"

