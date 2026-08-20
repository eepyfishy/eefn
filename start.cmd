@echo off
rem Starts the EEF node from its install directory.
cd /d %~dp0
python run_node.py %*
pause