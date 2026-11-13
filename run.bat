@echo off
rem Desktop calendar launcher: cd into this dir and start the app without console.
cd /d "%~dp0"
start "" pythonw calendar_app.py
