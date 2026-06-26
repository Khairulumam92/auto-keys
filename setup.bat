@echo off
echo ==============================
echo  auto-keys Windows Setup
echo ==============================
echo.

:: Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found. Install from https://python.org
    echo         Check "Add to PATH" during install
    pause
    exit /b 1
)

:: Check Chrome
where chrome >nul 2>&1
if %errorlevel% neq 0 (
    if not exist "C:\Program Files\Google\Chrome\Application\chrome.exe" (
        if not exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" (
            echo [WARN] Chrome not found. Install from https://chrome.google.com
            echo.
        )
    )
)

:: Install deps
echo.
echo Installing dependencies...
pip install -r requirements.txt

echo.
echo ==============================
echo  Setup complete!
echo ==============================
echo.
echo Run the TUI:
echo   python tui.py --count 45 --no-headless
echo.
echo Or test with 3 accounts first:
echo   python tui.py --count 3 --no-headless
echo.
pause
