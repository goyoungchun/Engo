@echo off
rem Engo 실행. 콘솔 창 없이 뜨도록 pythonw 를 씁니다.
setlocal
set HERE=%~dp0
if exist "%HERE%.venv\Scripts\pythonw.exe" (
    start "" "%HERE%.venv\Scripts\pythonw.exe" "%HERE%run.py" %*
) else (
    start "" pythonw "%HERE%run.py" %*
)

