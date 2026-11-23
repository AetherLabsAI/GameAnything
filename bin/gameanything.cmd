@echo off
rem gameanything launcher for Windows cmd and PowerShell in a clone or a plugin install (bin/gameanything is the bash one).
rem Put this bin folder on PATH, then run gameanything as usual (m2w.cmd, the old name, runs this file). Order: <root>\.venv, then uv (an editable install of <root> in
rem the uv cache; set GAMEANYTHING_NO_UV=1 or M2W_NO_UV=1 to skip it), then python on PATH with <root> on PYTHONPATH (needs: pip install -e <root>).
setlocal
rem The repo root without a trailing backslash: in "C:\path\" the \" escapes the closing quote for uv and python.
rem No cd: relative paths stay those of the caller.
for %%I in ("%~dp0..") do set "GAMEANYTHING_ROOT=%%~fI"
if exist "%GAMEANYTHING_ROOT%\.venv\Scripts\gameanything.exe" goto venv
if exist "%GAMEANYTHING_ROOT%\.venv\Scripts\m2w.exe" goto venvold
if defined GAMEANYTHING_NO_UV goto python
if defined M2W_NO_UV goto python
where uv >nul 2>&1 || goto python
rem --python: pyproject's requires-python (tests/test_packaging.py); --no-project alone takes uv's newest Python, which may lack wheels
uv run --quiet --no-project --python ">=3.10,<3.15" --with-editable "%GAMEANYTHING_ROOT%" gameanything %*
exit /b %ERRORLEVEL%

:venv
"%GAMEANYTHING_ROOT%\.venv\Scripts\gameanything.exe" %*
exit /b %ERRORLEVEL%

:venvold
"%GAMEANYTHING_ROOT%\.venv\Scripts\m2w.exe" %*
exit /b %ERRORLEVEL%

:python
if defined PYTHONPATH (set "PYTHONPATH=%GAMEANYTHING_ROOT%;%PYTHONPATH%") else set "PYTHONPATH=%GAMEANYTHING_ROOT%"
where python >nul 2>&1 || goto nopython
python -m gameanything %*
exit /b %ERRORLEVEL%

:nopython
echo gameanything: neither uv nor python is on PATH. Install uv: https://docs.astral.sh/uv/ 1>&2
exit /b 1
