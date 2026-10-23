@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
title Lyric Video Maker - Arabic / English
cd /d "%~dp0"

set "FFMPEG_DIR=D:\2 - Programmes\FFmpeg\FFmpeg\bin"
set "SCRIPT=lyric_video.py"

echo ============================================
echo   Lyric Video Maker  - Arabic / English
echo ============================================
echo.

if not exist "%FFMPEG_DIR%\ffmpeg.exe" goto :ffmpeg_fallback
set "PATH=%FFMPEG_DIR%;%PATH%"
echo [ok] ffmpeg: %FFMPEG_DIR%\ffmpeg.exe
goto :ffmpeg_done

:ffmpeg_fallback
echo [!] ffmpeg.exe not found in "%FFMPEG_DIR%"
echo     Edit FFMPEG_DIR at the top of this .bat file, or add ffmpeg to PATH.
where ffmpeg >nul 2>nul
if errorlevel 1 (
    echo [x] ffmpeg is not on PATH either.
    pause
    exit /b 1
)
echo [ok] using ffmpeg from PATH

:ffmpeg_done

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
    echo [x] Python 3 is not installed.
    echo     Get it from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
    pause
    exit /b 1
)
echo [ok] python: %PY%

echo.
echo Installing / checking Python packages...
%PY% -m pip install --disable-pip-version-check --quiet --upgrade -r requirements.txt
if errorlevel 1 (
    echo [x] pip install failed. Check your internet connection and try again.
    pause
    exit /b 1
)
echo [ok] packages ready
echo.

echo Choose language:
echo   1 = Arabic
echo   2 = English
echo.
choice /c 12 /n /m "Press 1 or 2: "
if errorlevel 2 (set "LYRLANG=en" & set "LANGNAME=English") else (set "LYRLANG=ar" & set "LANGNAME=Arabic")
echo [ok] %LANGNAME%
echo.

echo Choose template:
echo   1 = New style: black and white, words slide in with glow
echo   2 = Old style: colors (you choose light and dark colors next)
echo.
choice /c 12 /n /m "Press 1 or 2: "
if errorlevel 2 (set "STYLE=classic" & set "STYLENAME=Old style, colors") else (set "STYLE=mono" & set "STYLENAME=New style, black and white")
echo [ok] %STYLENAME%
echo.

echo Video is always 16:9. Choose quality:
echo   1 = HD     720p   1280x720   (10 Mbps, fastest)
echo   2 = FHD    1080p  1920x1080  (20 Mbps)
echo   3 = 2K     1440p  2560x1440  (40 Mbps)
echo   4 = 4K     2160p  3840x2160  (60 Mbps, slowest)
echo.
choice /c 1234 /n /m "Press 1, 2, 3 or 4: "
set "QUALITY=720p"
set "SIZE=1280x720"
if errorlevel 2 (set "QUALITY=fhd" & set "SIZE=1920x1080")
if errorlevel 3 (set "QUALITY=2k" & set "SIZE=2560x1440")
if errorlevel 4 (set "QUALITY=4k" & set "SIZE=3840x2160")
echo [ok] 16:9 %SIZE%, 60 fps
echo.

echo A window will open: choose the song (MP3 or MP4).
echo The .srt with the same name in that folder is picked automatically,
echo otherwise a second window asks for the .srt file.
echo.
%PY% "%SCRIPT%" --ffmpeg "%FFMPEG_DIR%" --lang %LYRLANG% --style %STYLE% --fps 60 --quality %QUALITY% %*
if errorlevel 1 (
    echo.
    echo [x] Render failed. See the message above.
)
echo.
pause
