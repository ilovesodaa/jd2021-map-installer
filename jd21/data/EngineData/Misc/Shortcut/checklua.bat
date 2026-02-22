@echo off

FOR /F "tokens=2* delims=	 " %%A IN ('REG QUERY "HKEY_CURRENT_USER\Software\Ubisoft\UbiArt\UAF" /v rootDir') DO SET UAF_RootDir=%%B

for /f %%x IN ('dir /s /b x:\RaymanOriginsProduction\*.lua') do call "%UAF_RootDir%\externtools\luac.exe" -p %%x

pause