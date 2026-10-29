@echo off
rem SPDX-License-Identifier: MIT
rem Copyright (c) 2026 Outthinkx by Luca De Simoni
rem Double-click to start the Meeting Notetaker (Windows test setup)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-notetaker.ps1"
if errorlevel 1 pause
