@echo off
REM Get the directory of this batch script.
set "APP_PATH=%~dp0"

REM Path to the server executable, assuming this script is in the same dir as AkServer.exe
set "SERVER_EXE=%APP_PATH%AkServer.exe"

REM Change to the application directory
pushd "%APP_PATH%"

REM Start the server.
echo Starting AkServer automatically... > "%TEMP%\AkServer_Startup_Log.txt"
start "AkServerAutoStart" /B "%SERVER_EXE%" >> "%TEMP%\AkServer_Startup_Log.txt" 2>&1

popd
exit
