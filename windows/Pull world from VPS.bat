@echo off
rem Double-click this (or a desktop shortcut to it). Extra arguments are passed on,
rem e.g. make a copy with:  ... pull-world.ps1" -World "Other World" -Server creative
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0pull-world.ps1" %*
pause
