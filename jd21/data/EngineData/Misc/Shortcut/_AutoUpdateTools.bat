FOR /F "tokens=2* delims=	 " %%A IN ('REG QUERY "HKEY_CURRENT_USER\Software\Ubisoft\UbiArt\UAF" /v rootDir') DO SET UAF_RootDir=%%B
set UAF_RootDir=%UAF_RootDir:\\=\%

TortoiseProc.exe /command:update /path:"%UAF_RootDir%" /notempfile /closeonend:1