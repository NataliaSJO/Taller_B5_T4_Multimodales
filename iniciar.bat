@echo off
rem Arranca FondoClaro y abre el navegador. Doble clic sobre este archivo.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Falta el entorno. Sigue los pasos de "Arranque" del README.md.
    pause
    exit /b 1
)
rem La descarga de folletos sigue creciendo: se incorporan los nuevos en cada arranque.
if exist "folletos\indice.csv" ".venv\Scripts\python.exe" scripts\procesar_folletos.py folletos
if exist "..\datos\folletos\indice.csv" ".venv\Scripts\python.exe" scripts\procesar_folletos.py ..\datos\folletos
start "" "%~dp0index.html"
".venv\Scripts\python.exe" -m streamlit run app.py
pause
