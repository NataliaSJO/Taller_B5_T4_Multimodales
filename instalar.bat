@echo off
rem Prepara FondoClaro tras clonar el repositorio. Doble clic; despues usa iniciar.bat.
rem Funciona en cualquier equipo (CPU) y descarga 1,4 GB de modelos.
rem Para los modelos de GPU, ejecuta despues instalar_parte2_opcional.bat.
cd /d "%~dp0"

py -3.11 --version >nul 2>&1
if errorlevel 1 (
    echo Hace falta Python 3.11: https://www.python.org/downloads/
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" py -3.11 -m venv .venv
set PY=.venv\Scripts\python.exe
%PY% -m pip install --upgrade pip
%PY% -m pip install -r requirements.txt --only-binary=llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
if errorlevel 1 goto error
%PY% scripts\download_models.py
if errorlevel 1 goto error

rem El catalogo real no esta en el repositorio: se importa si esta junto al proyecto.
set CATALOGO=
if exist "catalogo_fondos.md" set CATALOGO=catalogo_fondos.md
if exist "..\datos\catalogo_fondos.md" set CATALOGO=..\datos\catalogo_fondos.md
if defined CATALOGO (
    %PY% scripts\import_catalog.py "%CATALOGO%"
    if errorlevel 1 goto error
)

rem Los folletos descargados (DFI, KID, fichas) se procesan si estan junto al proyecto.
set FOLLETOS=
if exist "folletos\indice.csv" set FOLLETOS=folletos
if exist "..\datos\folletos\indice.csv" set FOLLETOS=..\datos\folletos
if defined FOLLETOS (
    %PY% scripts\procesar_folletos.py "%FOLLETOS%"
    if errorlevel 1 goto error
)

echo.
echo Listo. Haz doble clic en iniciar.bat para abrir la aplicacion.
if not defined CATALOGO (
    echo No se ha encontrado catalogo_fondos.md: se usaran 10 fondos de ejemplo.
    echo Copialo a esta carpeta y vuelve a ejecutar instalar.bat, o importalo con:
    echo   %PY% scripts\import_catalog.py ruta\a\catalogo_fondos.md
)
echo Opcional, con tarjeta NVIDIA: instalar_parte2_opcional.bat
pause
exit /b 0

:error
echo.
echo La instalacion ha fallado. Revisa el mensaje de arriba.
pause
exit /b 1
