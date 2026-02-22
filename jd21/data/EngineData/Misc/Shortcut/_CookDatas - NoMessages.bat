FOR /F "tokens=2* delims=	 " %%A IN ('REG QUERY "HKEY_CURRENT_USER\Software\Ubisoft\UbiArt\UAF" /v rootDir') DO SET UAF_RootDir=%%B
PUSHD
cd ..\..
set RayRoot=%cd%
cd /d %UAF_RootDir%
UA_ResourceCooker.exe directory=%RayRoot%;all=1;silent=1
Popd