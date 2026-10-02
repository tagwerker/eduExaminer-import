@echo off
cd /d "%~dp0"

rem ============================================================
rem  Startet die Weboberflaeche "Excel -> eduExaminer".
rem  Der Browser geht von selbst auf. Zum Beenden dieses
rem  Fenster schliessen.
rem ============================================================

set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY (
  where python >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo FEHLER: Python ist nicht installiert oder nicht im PATH.
  echo.
  echo Python von https://www.python.org/downloads/ installieren und
  echo dabei "Add python.exe to PATH" ankreuzen.
  echo.
  pause
  exit /b 1
)

%PY% -c "import streamlit, openpyxl" >nul 2>&1
if errorlevel 1 (
  echo Einmalige Einrichtung, das dauert einen Moment...
  %PY% -m pip install --quiet --disable-pip-version-check -r requirements-app.txt
  if errorlevel 1 (
    echo FEHLER: Die Einrichtung ist fehlgeschlagen.
    pause
    exit /b 1
  )
)

echo.
echo   Die Oberflaeche oeffnet sich gleich im Browser.
echo   Dieses Fenster bitte offen lassen.
echo.
%PY% -m streamlit run app.py --browser.gatherUsageStats false
pause
