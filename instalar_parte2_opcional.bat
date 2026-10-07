@echo off
rem Parte 2, opcional: modelos de GPU. Ejecutar despues de instalar.bat.
rem Anade el filtro con Gemma 3 4B (el modelo decide criterios y elige entre 150 fondos)
rem y la pagina "Modelo unico" (Gemma 3n). Necesita una NVIDIA con 12 GB o mas.
rem Descarga unos 3 GB de PyTorch y 19 GB de modelos.
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Ejecuta primero instalar.bat.
    pause
    exit /b 1
)
where nvidia-smi >nul 2>&1
if errorlevel 1 (
    echo No se ha encontrado una tarjeta NVIDIA. Esta parte no sirve en este equipo;
    echo la aplicacion sigue funcionando con la instalacion basica.
    pause
    exit /b 1
)

set PY=.venv\Scripts\python.exe
rem PyTorch con CUDA sale de su propio indice; en PyPI solo esta la version de CPU.
%PY% -m pip install torch --index-url https://download.pytorch.org/whl/cu128
if errorlevel 1 goto error
%PY% -m pip install -r requirements-gpu.txt
if errorlevel 1 goto error
%PY% -c "import torch, sys; sys.exit(0 if torch.cuda.is_available() else 1)"
if errorlevel 1 (
    echo PyTorch se ha instalado pero no detecta la GPU. Actualiza el controlador de NVIDIA.
    pause
    exit /b 1
)
%PY% scripts\download_models.py --gpu --omni
if errorlevel 1 goto error

echo.
echo Listo. Abre la aplicacion con iniciar.bat: en "Especialistas" aparecera
echo "Gemma 3 4B en GPU" y la pagina "Modelo unico" estara disponible.
pause
exit /b 0

:error
echo.
echo La instalacion ha fallado. Revisa el mensaje de arriba.
pause
exit /b 1
