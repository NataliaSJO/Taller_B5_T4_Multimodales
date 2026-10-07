@echo off
rem Prepara FondoClaro tras clonar el repositorio. Doble clic; despues usa iniciar.bat.
rem   instalar.bat        version basica: funciona en cualquier equipo (CPU), descarga 1 GB
rem   instalar.bat gpu    anade los modelos de GPU (NVIDIA con 12 GB o mas), descarga 19 GB mas
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

if /i "%1"=="gpu" (
    %PY% -m pip install -r requirements-gpu.txt --extra-index-url https://download.pytorch.org/whl/cu128
    if errorlevel 1 goto error
    %PY% scripts\download_models.py --gpu --omni
) else (
    %PY% scripts\download_models.py
)
if errorlevel 1 goto error

echo.
echo Listo. Haz doble clic en iniciar.bat para abrir la aplicacion.
echo Sin el catalogo real se usan 10 fondos de ejemplo. Para importarlo:
echo   %PY% scripts\import_catalog.py ruta\a\catalogo_fondos.md
pause
exit /b 0

:error
echo.
echo La instalacion ha fallado. Revisa el mensaje de arriba.
pause
exit /b 1
