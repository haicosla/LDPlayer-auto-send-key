@echo off
echo Dang build LDLauncher - onedir mode...

pyinstaller --clean --onedir ^
    --icon=icon.ico ^
    --name=LDLauncher ^
    --add-data "action_groups.json;." ^
    --add-data "config.json;." ^
    --add-data "scheduled_jobs.json;." ^
    --hidden-import=win32gui ^
    --hidden-import=win32con ^
    --hidden-import=win32api ^
    --hidden-import=pyautogui ^
    main.py

echo.
echo Build hoan tat!
echo Thu muc output: dist\LDLauncher
pause