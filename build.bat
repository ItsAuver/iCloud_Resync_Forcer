@echo off
REM ─────────────────────────────────────────────────
REM  Build icloud_resync.py into a single portable .exe
REM  Requires: pip install pyinstaller
REM ─────────────────────────────────────────────────

REM Check for venv
if exist ".venv\Scripts\activate.bat" (
    echo Found .venv, activating...
    call .venv\Scripts\activate.bat
) else (
    echo WARNING: No .venv found. Using system Python instead.
    echo This may be missing required dependencies.
    echo.
    set /p "REPLY=Continue anyway? [y/N] "
    if /i not "%REPLY%"=="y" (
        echo Aborted.
        exit /b 1
    )
)

pip install pyinstaller 2>nul
pyinstaller --onefile --windowed --name "iCloud_ReSyncTool" icloud_resync.py

echo.
echo ── Done! Your .exe is in the "dist" folder. ──
pause
