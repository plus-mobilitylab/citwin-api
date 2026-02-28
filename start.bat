@echo off

rem usage: start.bat [CONDA_ENV] [API_PORT] [API_ROOT_PATH]

set CONDA_ENV=%1
set API_PORT=%2
set API_ROOT_PATH=%3

rem activate conda environment
call C:\ProgramData\miniconda3\Scripts\activate.bat "%CONDA_ENV%"

rem change to app directory
cd /d "%~dp0"

rem start uvicorn server
python -m uvicorn api.api:app --host localhost --port "%API_PORT%" --root-path "%API_ROOT_PATH%" --workers 1
