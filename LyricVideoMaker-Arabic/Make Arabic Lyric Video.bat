@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
title Arabic Lyric Video Maker
cd /d "%~dp0"

set "FFMPEG_DIR=D:\2 - Programmes\FFmpeg\FFmpeg\bin"
set "SCRIPT=lyric_video_ar.py"

echo ============================================
echo   Arabic Lyric Video Maker  (+ animated emoji)
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

echo Choose platform  (auto YouTube in 5 s):
echo   1 = YouTube: 1920x1080 (16:9)  [default]
echo   2 = TikTok, Reels or Shorts: 1080x1920 (9:16)
echo.
choice /c 12 /n /t 5 /d 1 /m "Press 1 or 2: "
if errorlevel 2 (
    set "FORMAT=tiktok"
) else (
    set "FORMAT=youtube"
)
echo [ok] %FORMAT%
echo.

echo Choose quality  (auto FHD in 5 s):
echo   1 = 720p        (10 Mbps, fastest)
echo   2 = FHD 1080p   (20 Mbps)  [default]
echo   3 = 2K  1440p   (40 Mbps)
echo   4 = 4K  2160p   (60 Mbps, slowest)
echo.
choice /c 1234 /n /t 5 /d 2 /m "Press 1, 2, 3 or 4: "
set "QUALITY=720p"
if errorlevel 2 set "QUALITY=fhd"
if errorlevel 3 set "QUALITY=2k"
if errorlevel 4 set "QUALITY=4k"
echo [ok] %QUALITY%, always 60 fps
echo.

echo A window will open: choose the song (MP3).
echo The SRT with the same name in that folder is picked automatically.
echo.
%PY% "%SCRIPT%" --ffmpeg "%FFMPEG_DIR%" --format %FORMAT% --fps 60 --quality %QUALITY% %*
if errorlevel 1 (
    echo.
    echo [x] Render failed. See the message above.
)
echo.
pause
