@echo off
rem Engo. Double-click this: it sets up whatever is missing, then starts.
rem bootstrap.py needs nothing but the standard library, so any Python works.
setlocal
set "HERE=%~dp0"

rem Already set up? Its own interpreter runs bootstrap, which sees there is
rem nothing to do and launches immediately -- no window, no delay.
if exist "%HERE%.venv\Scripts\pythonw.exe" (
    start "" "%HERE%.venv\Scripts\pythonw.exe" "%HERE%bootstrap.py" %*
    exit /b
)

rem First run: any Python on the machine can drive the setup window.
where pyw >nul 2>&1
if not errorlevel 1 (
    start "" pyw -3 "%HERE%bootstrap.py" %*
    exit /b
)
where pythonw >nul 2>&1
if not errorlevel 1 (
    start "" pythonw "%HERE%bootstrap.py" %*
    exit /b
)
where py >nul 2>&1
if not errorlevel 1 (
    start "" py -3 "%HERE%bootstrap.py" %*
    exit /b
)
where python >nul 2>&1
if not errorlevel 1 (
    start "" python "%HERE%bootstrap.py" %*
    exit /b
)

echo.
echo   Engo needs Python 3.10 or newer, and none was found.
echo   Engo 를 실행하려면 Python 3.10 이상이 필요합니다.
echo.
echo   https://www.python.org/downloads/
echo   (설치할 때 "Add python.exe to PATH" 를 꼭 체크하세요.)
echo.
pause
