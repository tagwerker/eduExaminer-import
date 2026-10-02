@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

rem ============================================================
rem  Excel  ->  eduExaminer-EXZ
rem
rem  Excel-Datei auf diese Datei ziehen und loslassen.
rem  Die fertige .exz landet NEBEN der Excel-Datei.
rem ============================================================

rem --- Einstellungen ------------------------------------------------
rem max. Punkte je Multiple-Choice-Frage
set "TOTAL=4"
rem Punkte je offener Frage
set "ESSAY=4"
rem Nachkommastellen
set "DECIMALS=3"
rem Strukturvorlage aus eduExaminer
set "TEMPLATE=vorlage\struktur-vorlage.exz"
rem Tabellenblatt; leer = erstes Blatt der Datei
set "SHEET="
rem auf --negative setzen, wenn Fragen unter 0 Punkte fallen duerfen
set "NEGATIVE="
rem ------------------------------------------------------------------

if "%~1"=="" goto :keinedatei

set "XLSX=%~1"
set "OUT=%~dpn1.exz"

if not exist "!XLSX!" (
  echo FEHLER: Datei nicht gefunden:
  echo   !XLSX!
  goto :fehler
)
if not exist "%TEMPLATE%" (
  echo FEHLER: Strukturvorlage fehlt: %TEMPLATE%
  echo.
  echo In eduExaminer einen Export erzeugen und dorthin legen:
  echo   Autor-Rolle -^> Kontextmenue an Frage/Topic -^> Export
  echo   -^> "Export to biz:Examiner format"
  goto :fehler
)

rem --- Python suchen ------------------------------------------------
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
  goto :fehler
)

%PY% -c "import openpyxl" >nul 2>&1
if errorlevel 1 (
  echo Einmalige Einrichtung: openpyxl wird installiert...
  %PY% -m pip install --quiet --disable-pip-version-check openpyxl
  if errorlevel 1 (
    echo FEHLER: openpyxl konnte nicht installiert werden.
    goto :fehler
  )
)

rem --- umwandeln ----------------------------------------------------
set "SHEETARG="
if not "%SHEET%"=="" set "SHEETARG=--sheet %SHEET%"

echo.
echo   %~nx1
echo.
%PY% -W ignore -m exz build "!XLSX!" %SHEETARG% --template "%TEMPLATE%" ^
  --total %TOTAL% --essay-points %ESSAY% --decimals %DECIMALS% %NEGATIVE% ^
  --outdir "%TEMP%\exz-zwischenschritt" --quiet -o "!OUT!"
if errorlevel 1 goto :fehler

echo.
echo   Fertig. Die Datei liegt neben der Excel-Datei:
echo   !OUT!
echo.
ping -n 5 127.0.0.1 >nul 2>&1
goto :ende

:keinedatei
echo.
echo   Excel  -^>  eduExaminer-EXZ
echo   ------------------------------------------------------------
echo.
echo   So wird es benutzt:
echo     Die Excel-Datei mit der Maus auf diese Datei ziehen
echo     ^("Excel-zu-EXZ.bat"^) und loslassen.
echo.
echo   Die fertige .exz-Datei liegt danach im selben Ordner wie
echo   die Excel-Datei und kann in eduExaminer hochgeladen werden:
echo     Autor-Rolle -^> Topics Questions -^> import
echo     -^> Reiter "bizExaminer file"
echo.
echo   Punkte: %TOTAL% je Multiple-Choice-Frage, %ESSAY% je offener Frage.
echo   Zum Aendern diese Datei mit dem Editor oeffnen ^(Zeilen oben^).
echo.
pause
goto :ende

:fehler
echo.
echo   Abgebrochen - siehe Meldung oben.
echo.
pause

:ende
endlocal
