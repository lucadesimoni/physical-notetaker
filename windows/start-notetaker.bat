@echo off
rem Double-click to start the Meeting Notetaker (Windows test setup)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-notetaker.ps1"
if errorlevel 1 pause
