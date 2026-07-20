@echo off
setlocal EnableExtensions
set "HERE=%~dp0"
set "PYEXE="
set "PYARG="

rem --- Already set up? Its own interpreter starts the program immediately. ---
if not exist "%HERE%.venv\Scripts\pythonw.exe" goto trypyw
"%HERE%.venv\Scripts\python.exe" -c "pass" >nul 2>&1
if errorlevel 1 goto trypyw
set "PYEXE=%HERE%.venv\Scripts\pythonw.exe"
goto run

rem --- First run: any Python 3 can drive the setup window. ---
rem Each candidate gets its own label. Note that "if cond set A & set B" would
rem run the second set unconditionally, which is how -3 ends up being passed
rem to an interpreter that never asked for it.

:trypyw
pyw -3 -c "pass" >nul 2>&1
if errorlevel 1 goto trypy
set "PYEXE=pyw"
set "PYARG=-3"
goto run

:trypy
py -3 -c "pass" >nul 2>&1
if errorlevel 1 goto trypath
set "PYEXE=py"
set "PYARG=-3"
goto run

:trypath
for %%I in (pythonw.exe) do if not "%%~$PATH:I"=="" call :check "%%~$PATH:I"
if defined PYEXE goto run
for %%I in (python.exe) do if not "%%~$PATH:I"=="" call :check "%%~$PATH:I"
if defined PYEXE goto run

rem The usual install locations, newest version first.
call :scan "%LOCALAPPDATA%\Programs\Python"
if defined PYEXE goto run
call :scan "%ProgramFiles%\Python"
if defined PYEXE goto run
call :scan "%ProgramFiles(x86)%\Python"
if defined PYEXE goto run
goto nopython

rem --- Is this candidate a Python we can actually use? ---
:check
if defined PYEXE goto :eof
set "CAND=%~1"
rem A Microsoft Store alias is a 0-byte stub that opens the Store instead of
rem running anything. Skip it, or the program never starts and never says why.
if "%~z1"=="0" goto :eof
if not "%CAND:WindowsApps=%"=="%CAND%" goto :eof
"%CAND%" -c "pass" >nul 2>&1
if errorlevel 1 goto :eof
set "PYEXE=%CAND%"
goto :eof

:scan
if not exist "%~1" goto :eof
for /f "delims=" %%D in ('dir /b /ad /o-n "%~1" 2^>nul') do call :trydir "%~1\%%D"
goto :eof

:trydir
if defined PYEXE goto :eof
if exist "%~1\pythonw.exe" call :check "%~1\pythonw.exe"
if defined PYEXE goto :eof
if exist "%~1\python.exe" call :check "%~1\python.exe"
goto :eof

:run
start "" "%PYEXE%" %PYARG% "%HERE%bootstrap.py" %*
goto done

:nopython
echo.
echo   Engo needs Python 3.10 or newer, and none was found on this computer.
echo.
echo   Install it from   https://www.python.org/downloads/
echo   During setup, tick "Add python.exe to PATH".
echo   Then run Engo.bat again.
echo.
pause

:done
endlocal
