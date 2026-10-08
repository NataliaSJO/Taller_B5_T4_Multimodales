# FondoClaro · asesor de fondos por voz (MVP)

**Equipo:** Josep Perez Segura, Emilio Sánchez Martínes y Natalia San José Ortega.

MVP del Taller B5-T4. El usuario **habla** con la página sobre lo que quiere invertir y la página le **responde con voz**. Si falta algún dato obligatorio, se lo pregunta. Al terminar entrega un **informe PDF** con la cartera de fondos propuesta y un **audio** que resume en qué le recomienda invertir. También se puede escribir en lugar de hablar.

Los modelos abiertos se descargan de Hugging Face y se ejecutan en local; el recorrido básico no necesita claves de API. Por defecto, la voz de respuesta envía texto a un servicio externo; si se activa Claude, también salen la conversación y los candidatos. Para una demostración con inferencia local, usar `VOICE=local`, un selector local o reglas y `ADVISOR_WEB=off`, después de descargar los modelos.

> Demostración educativa. No es asesoramiento de inversión, no sustituye un test de idoneidad y no verifica comisiones ni mínimos de suscripción. Las rentabilidades pasadas no garantizan rentabilidades futuras.

![Conversación manos libres: la página saluda y espera a que hables](docs/images/conversacion.png)

![Propuesta con reparto, informe PDF y audio resumen](docs/images/propuesta.png)

Las capturas están hechas con el catálogo sintético de demostración (`CATALOG=demo`): los fondos y sus cifras son ficticios.

## Correspondencia con el enunciado y entregables

Referencia: [enunciado del Taller B5-T4](Taller_B5_T4.pdf). La práctica pide un MVP FinTech interactivo, da más valor a la orquestación de modelos especializados y exige documentación y una demostración funcional. Las modalidades de su apartado 3 son ejemplos; no se presentan aquí como capacidades implementadas si no lo están.

| Requisito | Dónde se documenta o demuestra | Alcance y estado |
| --- | --- | --- |
| 4.1. Problema, público y propuesta de valor | [Idea y propuesta de valor](#el-problema-para-quién-y-por-qué-multimodal) y esquema Mermaid | Propuesta B2B2C; hipótesis de mercado pendiente de validar con asesores. |
| 4.1. Viabilidad técnica y económica | [Viabilidad](#viabilidad) | Costes, latencia, privacidad, marco financiero y monetización; se distinguen estimaciones de resultados comprobados. |
| 4.2. Diversidad de modalidades | [Entradas, modelos y salidas](#entradas-modelos-y-salidas) | Voz, texto y salidas de audio y PDF; documentos e históricos opcionales. Imagen disponible en Modelo único, sin evaluación real documentada. |
| 4.2. Orquestación de modelos | Diagramas de ambas versiones y [arquitectura por capas](#arquitectura-por-capas) | Especialistas es la versión principal para mostrar el encadenamiento; Modelo único es una comparación experimental. |
| 4.3. MVP, UI, UX y robustez | [Interfaz](#qué-hay-en-la-página), capturas y [validación](#validación-y-resultados) | Conversación, corrección de perfil, navegación, errores y respaldos. Las pruebas automáticas no sustituyen la prueba de voz real. |
| 4.3. Arranque directo y dependencias | [Arranque](#arranque-tras-clonar-windows), `instalar.bat`, `iniciar.bat` y `requirements*.txt` | Recorrido básico con datos sintéticos; instalación de GPU y datos privados opcional. |
| 4.4. README, capturas, diagramas y pitch técnico | Este README y [pitch de cinco diapositivas](docs/pitch_fondoclaro_v3.pptx) | Archivos incluidos en el repositorio. |
| 4.4. Modularidad | [Arquitectura por capas](#arquitectura-por-capas) y [estructura](#estructura) | Separación de interfaz, negocio, datos y acceso a modelos. |
| 5.1. Repositorio del MVP | [Repositorio en GitHub](https://github.com/NataliaSJO/Taller_B5_T4_Multimodales) | Código y datos sintéticos incluidos; datos privados y pesos de modelos no se distribuyen. |
| 5.2. Demostración funcional | [Guion de demostración](#demostración-funcional-para-la-entrega) | Modalidad prevista: demo interactiva local. No se aporta aquí una URL pública ni una grabación; debe ejecutarse ante el evaluador o adjuntarse un vídeo. |

**Entrega académica:** grupo de tres estudiantes; entrega mediante el aula virtual el **8 de octubre de 2026 a las 18:00**, según el enunciado. Antes de entregar, comprobar que el enlace del aula apunta a la versión que se va a demostrar.

## El problema, para quién y por qué multimodal

```mermaid
flowchart LR
    subgraph P[El problema]
        P1[Miles de clases de fondos<br/>92.257 en el catálogo]
        P2[Información dispersa:<br/>precios, folletos en PDF, fichas]
        P3[Quien ahorra habla de plazos y miedos,<br/>no de volatilidad ni de Sharpe]
    end
    subgraph S[FondoClaro]
        S1[Conversación por voz<br/>como con un asesor]
        S2[Lee precios diarios y folletos<br/>y aplica el perfil a todo el catálogo]
        S3[Cartera explicada:<br/>informe PDF y resumen hablado]
    end
    subgraph C[Para quién]
        C1[Asesores y redes de oficinas<br/>B2B2C: preparan la reunión con el cliente]
        C2[El cliente final recibe<br/>una propuesta que entiende]
    end
    P --> S --> C
```

- **Problema.** Elegir fondos exige traducir una necesidad cotidiana («tengo 20.000 euros para diez años y no quiero sustos») a filtros técnicos, y cruzar datos que están en formatos distintos: series de precios, folletos en PDF, fichas comerciales.
- **Público objetivo: B2B2C.** El usuario es el asesor o el gestor de una entidad que ya tiene autorización y controles de idoneidad; el beneficiario es su cliente. No se plantea como servicio directo al público (ver «Normativa»).
- **Qué aporta la multimodalidad.** La voz elimina el formulario: quien no sabe qué es la volatilidad puede explicar lo que quiere y contestar preguntas. Los documentos (DFI, KID, fichas) aportan lo que no está en los precios: riesgo oficial, costes y mínimos. Las series temporales dicen cómo se mueven los fondos entre sí. Y la salida vuelve a ser multimodal: una explicación hablada para el momento y un PDF con gráficos para decidir después.

## Viabilidad

**Coste de inferencia y APIs.** Con modelos locales y `VOICE=local` no hay facturación de un proveedor por llamada, pero sí consumo eléctrico, amortización del equipo, mantenimiento y licencias de datos. La voz en línea depende de un servicio externo no oficial: no se asume disponibilidad garantizada ni un contrato de servicio. Claude es opcional y se factura aparte; no se ha validado aquí su tarifa ni la disponibilidad del identificador de modelo configurado.

Para presupuestar una API: `coste = tokens_entrada / 1.000.000 × tarifa_entrada + tokens_salida / 1.000.000 × tarifa_salida`, sumando **todas** las llamadas de criterios, selección, criba, reintentos y herramientas web. Como ejemplo de volumen, la documentación previa estimaba 6.600 tokens de entrada y 300 de salida para una petición; no debe tomarse como coste total medido de una conversación. Las tarifas se deben consultar al contratar el proveedor. El coste mensual local puede estimarse como `amortización + mantenimiento + licencias + kW medios × horas de uso × precio del kWh`. No se ha medido todavía el consumo eléctrico.

**Referencia de latencias** (RTX 5080, modelos ya cargados). Los siguientes tiempos proceden de las pruebas descritas en versiones anteriores del proyecto; no se han reproducido en esta revisión ni se adjunta un registro de benchmark. Son orientativos, no una garantía para otro equipo:

| Paso | Tiempo |
| --- | --- |
| Transcribir un turno | 0,1 s en GPU (Whisper large-v3-turbo); alrededor de 1 s en CPU (Whisper small) |
| Entender y preguntar (reglas) | menos de 1 s, más 1–2 s de voz |
| Decidir criterios (Gemma 3 4B) | unos 10 s |
| Filtrar el catálogo, búsqueda semántica e histórico diario de hasta 2.000 candidatos | 4–6 s |
| Elegir y repartir (Gemma 3 4B) | unos 8 s |
| Informe y voz del resumen | 3–5 s |
| **Propuesta completa, hecha de una vez** | **20–35 s** |
| **Propuesta tras conversar por voz** (lo adelantado en segundo plano) | **unos 11 s** |

Una conversación de tres turnos por voz tarda en total unos 80 s. En cuanto se conocen plazo, riesgo y divisa, un hilo en segundo plano decide los criterios, filtra el catálogo y lee el histórico mientras la página hace las preguntas de asesor; cuando el cliente contesta solo queda elegir. Si responde de inmediato (por escrito), la espera vuelve a ser de unos 20 s. Sin GPU el modelo es más pequeño y ve menos candidatos, a costa de calidad.

**Objetivo de UX, pendiente de medir sistemáticamente.** Con modelos cargados, se busca responder a las preguntas de perfil en unos 3 s y generar la propuesta en unos 30 s; la carga inicial se mide aparte. Para comprobarlo, ejecutar la misma conversación al menos diez veces por configuración y registrar mediana, percentil 95, errores y uso de respaldos. La aplicación muestra el tiempo por turno, pero aún no aporta este benchmark completo.

**Marco financiero.** La CNMV describe las recomendaciones personalizadas sobre productos como asesoramiento y exige evaluar conocimientos, experiencia, situación financiera y objetivos del cliente. Las preguntas de este MVP no constituyen una evaluación completa de idoneidad. Un uso comercial requeriría concretar el servicio con una entidad autorizada y revisar sus obligaciones; elegir B2B2C no acredita por sí mismo cumplimiento. Referencias: [asesoramiento](https://www.cnmv.es/portal/inversor/asesoramiento?lang=es) y [evaluación de idoneidad](https://internet.cnmv.es/portal/inversor/idoneidad?lang=es), consultadas el 08/10/2026.

**Privacidad y datos.** La aplicación procesa transcripciones, preferencias y audio, que pueden contener datos personales. Whisper transcribe en local y elimina el archivo temporal; la conversación y los audios de respuesta permanecen en el estado de sesión y el usuario puede descargar documentos. `VOICE=auto` puede enviar el texto de respuesta a Microsoft; Claude recibe conversación y candidatos si se activa. La demo debe usar datos ficticios. Antes de un uso con clientes habría que definir base jurídica, información al interesado, conservación, control de acceso y condiciones de los proveedores, siguiendo la [protección de datos por defecto de la AEPD](https://www.aepd.es/derechos-y-deberes/cumple-tus-deberes/medidas-de-cumplimiento/proteccion-de-datos-por-defecto), consultada el 08/10/2026. No se ha realizado una auditoría de cumplimiento. El catálogo EODHD y los documentos externos requieren comprobar sus derechos de uso y redistribución.

**Monetización y validación de mercado.** Hipótesis: licencia por puesto de asesor o por oficina, con procesamiento local y servicios externos desactivados cuando se requiera mantener los datos en la infraestructura de la entidad. El valor propuesto es reducir tiempo de preparación y hacer comprensible la propuesta. Falta validar precios y disposición a pagar. El siguiente paso sería entrevistar a asesores y realizar un piloto con casos ficticios, comparando tiempo de preparación, correcciones necesarias y comprensión del informe frente al procedimiento habitual.

## Requisitos

| | Instalación básica (`instalar.bat`) | Con modelos de GPU (`instalar_parte2_opcional.bat`) |
| --- | --- | --- |
| Sistema | Windows 10 u 11 de 64 bits | El mismo |
| Python | 3.11, con el lanzador `py` (viene con el instalador de python.org) | El mismo |
| Procesador y memoria (orientativo, no medido) | Cualquier CPU reciente; 8 GB de RAM | 16 GB de RAM |
| Tarjeta gráfica | No hace falta | NVIDIA con 12 GB de memoria o más y controlador reciente (se instala PyTorch para CUDA 12.8) |
| Disco | 2 GB (entorno 0,7 GB y modelos 1,3 GB) | unos 26 GB más (PyTorch con CUDA, 5 GB, y 21 GB de modelos) |
| Internet | Para instalar y para la primera vez que se procesan los folletos (descarga el modelo de embeddings); después solo para la voz neuronal | Para instalar |
| Navegador | Chrome o Edge recientes, con permiso de micrófono | El mismo |
| Datos | `catalogo_fondos.md` y, opcionalmente, la carpeta `folletos/` y `fondos_diarios.parquet` (no están en el repositorio); sin catálogo se usan 10 fondos de ejemplo | Los mismos |

Con la instalación básica funciona toda la conversación por voz, el informe y el audio; la voz se transcribe con Whisper `small` y los fondos los elige Gemma 3 1B en CPU entre 10 líneas, sin el paso de criterios. La parte 2 añade Whisper `large-v3-turbo` en GPU, el modelo que decide los criterios y elige entre 150 líneas (Gemma 3 4B) y la página «Modelo único» (Gemma 3n).

## Arranque tras clonar (Windows)

1. Copia a la carpeta del proyecto `catalogo_fondos.md` y, si los tienes, la carpeta `folletos/` y `fondos_diarios.parquet` (ninguno está en el repositorio). También se encuentran solos si están en una carpeta `datos` junto al proyecto. Sin el catálogo se usan 10 fondos sintéticos de ejemplo.
2. Doble clic en **`instalar.bat`**. Crea el entorno, instala las dependencias, descarga los modelos básicos (1,3 GB), importa el catálogo y procesa los folletos si los encuentra (la primera vez, unos minutos más para el índice de búsqueda semántica). Funciona en cualquier equipo, sin GPU.
3. Doble clic en **`iniciar.bat`**. Arranca la aplicación y abre `index.html`, la puerta de entrada con los enlaces.
4. Opcional, solo con una NVIDIA de 12 GB o más: doble clic en **`instalar_parte2_opcional.bat`**. Instala PyTorch con CUDA y descarga 21 GB de modelos. Añade Whisper `large-v3-turbo`, el filtro con Gemma 3 4B y la versión de modelo único.

La aplicación queda en `http://localhost:8501`. Clona el proyecto en una ruta corta (por ejemplo `C:\proyectos\`): en rutas muy largas la instalación falla por el límite de Windows.

Para importar el catálogo más tarde: `.venv\Scripts\python scripts\import_catalog.py ruta\a\catalogo_fondos.md`.

A mano, sin los `.bat`:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt --only-binary=llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
.venv\Scripts\python scripts\download_models.py
.venv\Scripts\python -m streamlit run app.py
```

En la página **Pruebas y estado** se ve qué está instalado y qué falta, y se pueden ejecutar las pruebas automáticas desde el navegador.

## Demostración funcional para la entrega

La modalidad elegida es una **demo interactiva local**, admitida por el apartado 5.2 del enunciado. El repositorio permite prepararla sin los datos privados. Las capturas y las pruebas automáticas son evidencias complementarias; no sustituyen mostrar el funcionamiento con los modelos y el micrófono. No se incluye una grabación ni un despliegue público en esta entrega documental.

Después de ejecutar `instalar.bat`, abrir PowerShell en la carpeta del proyecto y arrancar una sesión con datos ficticios y voz local:

```powershell
$env:CATALOG = "demo"
$env:VOICE = "local"
$env:AI_FILTER = "auto"
$env:ADVISOR_WEB = "off"
.\.venv\Scripts\python -m streamlit run app.py
```

Estas variables se aplican a esa terminal y prevalecen sobre `.env`. Abrir `http://localhost:8501`, permitir el micrófono y comprobar en **Pruebas y estado** que Whisper, Piper y al menos un selector de lenguaje están disponibles. En CPU, elegir Gemma 3 1B; en GPU, Gemma 3 4B. Si solo aparecen reglas, se puede verificar la interfaz, pero no se estará demostrando el encadenamiento completo de modelos.

| Paso de la demo, unos 3–5 minutos | Acción | Resultado que debe comprobarse |
| --- | --- | --- |
| 1. Identificar configuración | Mostrar Especialistas, el catálogo sintético y los modelos de la barra lateral. | Queda claro qué datos y modelos se están usando. |
| 2. Entrada de voz | Activar manos libres o pulsar para hablar: «Quiero invertir diez mil euros». | Se transcribe la petición y se preguntan los datos obligatorios que faltan. |
| 3. Conversación | Contestar: «A cinco años, riesgo medio». Después: «Quiero hacer crecer el dinero, tengo experiencia y esperaría si cae». | El perfil se completa; se activan los criterios cuando el selector lo permite y se eligen fondos del catálogo. |
| 4. Salidas | Escuchar el resumen, mostrar la tabla y descargar PDF y audio. | La propuesta tiene fondos, pesos e importes; el informe contiene gráficos y explica los límites de los datos sintéticos. |
| 5. Corrección y robustez | Escribir «No quiero riesgo alto, prefiero riesgo bajo» o editar el perfil; después probar «menos cien euros» y corregirlo a «diez mil euros». | Se respeta la corrección de riesgo, se pide aclaración del importe inválido y se puede continuar. |
| 6. Comparación opcional | Con GPU, repetir la conversación en Modelo único. | Se observan diferencias de tiempo y extracción; no se presenta esta variante como superior sin medirla. |

Para mostrar la búsqueda en folletos y el histórico, realizar una segunda demo con datos autorizados: reiniciar sin `CATALOG=demo`, importar los documentos y comprobar que se detecta el Parquet. Esas capacidades **no se activan con los diez fondos ficticios**. Si se elige una grabación en vez de la demo en vivo, debe mostrar estos pasos y añadirse al aula o enlazarse desde el repositorio con permiso de acceso.

El [pitch técnico de cinco diapositivas](docs/pitch_fondoclaro_v3.pptx) acompaña la presentación. Su texto abreviado debe leerse con los límites de costes, latencias y privacidad de este README; el uso local no elimina el coste de operación y la voz en línea sí envía texto fuera del equipo.

## Validación y resultados

Para ejecutar la batería automática sin inferencias reales:

```powershell
.\.venv\Scripts\python -m unittest discover -s tests -v
```

**Comprobación del 08/10/2026:** 89 pruebas ejecutadas, todas correctas. Cubren extracción y diálogo, negaciones, restricciones, reparto, importes, PDF, agrupación y criba, además de flujos de las dos páginas con modelos simulados. El recorrido de datos sintéticos permite repetir estas comprobaciones sin el catálogo privado.

Esta ejecución no verifica reconocimiento de voz real, calidad de Gemma, disponibilidad de Claude, el servicio de voz en línea, la instalación en un equipo limpio ni el histórico privado completo. Los mensajes de Streamlit durante las pruebas incluyen una advertencia de obsolescencia de `st.components.v1.html`; no produjo fallos, pero queda pendiente migrar ese uso.

![Página de comprobaciones de la aplicación](docs/images/pruebas.png)

La captura ilustra la página de estado; el resultado actual de la revisión es el indicado arriba. La comparación de modelos y los tiempos de otras secciones son observaciones previas, no resultados de esta batería. Para evaluar calidad real se necesita un conjunto de conversaciones etiquetadas y registrar campos extraídos correctamente, restricciones respetadas, propuestas completadas, uso de respaldos y latencia por etapa.

## Qué hay en la página

| Página | Qué es |
| --- | --- |
| 🧩 **Especialistas** | Un modelo adaptado a cada paso. En la barra lateral se elige quién selecciona los fondos (Gemma 3 4B en GPU, Gemma 3 1B en CPU, Claude por API o solo reglas; aparecen las opciones instaladas) y quién entiende lo que dices (reglas, o reglas más el modelo de lenguaje). |
| 🧠 **Modelo único** | Un solo modelo multimodal (Gemma 3n) recibe audio, texto o imagen y hace todo. Necesita GPU. |
| ✅ **Pruebas y estado** | Qué modelos y datos hay instalados, y las pruebas automáticas. |

Hay tres formas de conversar, que se eligen encima del micrófono:

- **🎧 Manos libres** (por defecto): se pulsa «Empezar conversación» una vez. La página habla, escucha hasta que te callas, envía sola y vuelve a escuchar cuando termina de responder. No oye mientras habla, así que no se la puede interrumpir.
- **🎙️ Pulsar para hablar:** pulsar, hablar y volver a pulsar para enviar.
- **⌨️ Escribir:** chat de texto, donde también se pueden adjuntar audios.

En la barra lateral, «Perfil interpretado (editable)» muestra lo que la página ha entendido y permite corregirlo a mano; al aplicar los cambios se recalcula la propuesta. Cada versión conserva su propia conversación al pasar de una a otra. Si la voz o el PDF fallan, la propuesta se muestra igualmente en pantalla.

**Voz.** Las respuestas usan una voz neuronal en línea (`es-ES-ElviraNeural`, a través del paquete `edge-tts`). Envía el texto de cada respuesta al servicio de voz de Microsoft y no es una API oficial. Con `VOICE=local` en `.env`, o si falla la conexión, se intenta usar Piper. Esta opción evita el envío de texto para sintetizar voz, pero no desactiva Claude si se ha seleccionado por separado.

**Entender lo que dices.** Por defecto lo hacen unas reglas en español, instantáneas. Con «Reglas + modelo de lenguaje», Gemma 3 4B lee además cada frase. En una prueba con ocho frases coloquiales el modelo captó cosas que las reglas no («bolsa americana», importes en letra), pero tardó 8–13 s por turno, se equivocó en algún dato y rellenó rasgos que nadie había dicho; por eso solo se le toman plazo, riesgo, divisa, importe, zona y sector, y las reglas tienen la última palabra.

**Conversación de prueba:** «Quiero invertir 10.000 euros en fondos de tecnología, bien diversificado» → «A cinco años y con riesgo alto» → «Quiero hacer crecer el dinero, nunca he invertido y si cae vendería».

**Cambiar el aspecto:** `estilo.css` (burbujas, títulos) y `.streamlit/config.toml` (colores, tipografía, puerto). `index.html` es solo la portada con los enlaces; la aplicación es Python y no funciona abriendo un HTML sin arrancarla.

## Entradas, modelos y salidas

Hay un diagrama por versión. Cada cuadro indica el paso, el modelo integrado en el código y, cuando procede, una alternativa sin probar. La disponibilidad depende de la instalación. Los cuadros «sin modelo» son código; sus gráficos y PDF no cuentan como generación de imágenes mediante un modelo.

| Modalidad | Implementación | Límite de la evidencia |
| --- | --- | --- |
| Audio → texto | Whisper en Especialistas; Gemma 3n en Modelo único. | Requiere modelos descargados y prueba real con micrófono. |
| Texto → decisiones estructuradas | Gemma propone criterios y selección; el código valida y calcula las cifras. | CPU omite criterios; «Solo reglas» omite el modelo de lenguaje. |
| Texto → audio | Voz en línea o Piper local. | Gemma 3n no genera el audio de respuesta. |
| Documento → texto y búsqueda | Extracción de PDF/HTML con reglas y embeddings MiniLM sobre los objetivos. | Es extracción textual, no OCR ni comprensión visual de páginas escaneadas. Requiere folletos externos. |
| Datos tabulares/series → gráficos y PDF | Catálogo, histórico opcional y ReportLab. | Salida multimedia programática; no hay un modelo de texto a imagen. |
| Imagen → texto | Entrada de imagen en Gemma 3n. | Interfaz implementada; evaluación real de imágenes pendiente. |

La cadena principal para demostrar pluralidad de modelos es **Whisper → Gemma → Piper** (o voz en línea), con filtros deterministas entre etapas y MiniLM cuando hay folletos. Modelo único comparte herramientas y voz externa: el nombre describe el modelo de comprensión y selección, no la eliminación de todos los demás componentes.

## Arquitectura por capas

| Capa | Responsabilidad | Módulos principales |
| --- | --- | --- |
| Interfaz y sesión | Navegación, micrófono, chat, edición del perfil, reproducción y descargas. | `app.py`, `paginas/`, `src/ui.py`, `componentes/manos_libres/` |
| Acceso a modelos | Transcripción, generación, embeddings, extracción opcional y síntesis de voz. | `src/audio.py`, `src/hf_model.py`, `src/ai_filter.py`, `src/omni.py`, `src/extraction.py`, `src/semantic.py`, `src/tts.py` |
| Lógica de negocio | Diálogo, preferencias, restricciones, ranking, validación y reparto monetario. | `src/conversation.py`, `src/preferences.py`, `src/recommender.py`, `src/money.py`, `src/models.py` |
| Datos y coordinación | Importación, folletos, series y preparación de candidatos en segundo plano. | `scripts/`, `src/catalog.py`, `src/brochures.py`, `src/history.py`, `src/screening.py` |
| Presentación de resultados | Resumen hablado, informe y gráficos calculados a partir de los datos. | `src/report.py` |

Los modelos devuelven preferencias, criterios o identificadores de candidatos; el código aplica filtros y valida el reparto antes de presentar resultados. `src/ui.py` coordina las capas y `src/ai_filter.py` combina adaptadores con validación: es una separación modular de MVP, no una arquitectura de servicios independientes. Si falla la selección del modelo se usan reglas; si falla la voz o el PDF se conserva la propuesta en pantalla. La ausencia de históricos y folletos reduce las capacidades sin impedir el recorrido con datos sintéticos.

Los diagramas siguientes detallan el flujo de datos de las dos versiones.

### Versión Especialistas: un modelo adaptado a cada paso

```mermaid
flowchart LR
    subgraph IN[Entradas]
        direction TB
        I1[🎙️ Micrófono, manos libres<br/>entrada principal]
        I2[📎 Audio adjunto<br/>wav, mp3, m4a, ogg…]
        I3[⌨️ Texto escrito]
        I4[(Catálogo EODHD<br/>92.257 fondos)]
        I5[(📑 Folletos: DFI, KID, fichas<br/>PDF y HTML)]
        I6[(📈 Histórico diario<br/>Parquet, 317 millones de filas)]
    end

    subgraph MOD[Modelos, en cadena]
        direction TB
        E1[Voz a texto<br/>Whisper large-v3-turbo en GPU · small en CPU<br/>alternativa: Parakeet TDT v3]
        E2[Extraer preferencias y preguntar<br/>Reglas en español · opcional Gemma 3 4B<br/>alternativa: Gemma 3 12B o Claude Haiku 4.5]
        E3[Decidir criterios de búsqueda<br/>Gemma 3 4B en GPU<br/>alternativa: Gemma 3 12B o Claude Opus 5.5]
        E4[Búsqueda semántica en folletos<br/>MiniLM multilingüe en CPU<br/>alternativa: bge-m3]
        E5[Filtrar el catálogo, caídas y grupos de fondos parecidos<br/>sin modelo]
        E6[Elegir y repartir, una línea por grupo<br/>Gemma 3 4B en GPU · respaldo Gemma 3 1B en CPU<br/>alternativa: Gemma 3 12B o Claude Opus 5.5]
        E1 --> E2 --> E3 --> E4 --> E5 --> E6
    end

    subgraph VOZ[De texto a voz]
        direction TB
        T1[Redactar lo que se va a decir<br/>plantillas con las cifras de los datos<br/>sin modelo]
        T2[Texto a voz<br/>es-ES-ElviraNeural con edge-tts, en línea<br/>respaldo: Piper es_ES-davefx-medium, local en CPU<br/>alternativa local: Kokoro o XTTS-v2]
        T1 --> T2
    end

    subgraph OUT[Salidas]
        direction TB
        O1[🔊 Audio WAV que suena solo<br/>en el navegador]
        O2[📄 Informe PDF con gráficos<br/>ReportLab, sin modelo]
        O3[🔊 Audio resumen descargable]
        O4[🖥️ Tabla, perfil editable y avisos en pantalla<br/>sin modelo]
    end

    I1 --> E1
    I2 --> E1
    I3 --> E2
    I4 --> E5
    I5 -- leídos con reglas --> E4
    I5 -- riesgo oficial, costes, mínimos --> E5
    I6 --> E5
    E2 -- falta un dato: pregunta --> T1
    E6 -- fondos y pesos --> T1
    T2 --> O1
    T2 --> O3
    E6 --> O2
    E6 --> O4
    I6 -- evolución real y escenarios --> O2
```

### Versión Modelo único: un solo modelo multimodal

```mermaid
flowchart LR
    subgraph IN2[Entradas]
        direction TB
        J1[🎙️ Micrófono, manos libres]
        J2[📎 Audio adjunto<br/>wav, mp3, flac, ogg]
        J3[⌨️ Texto escrito]
        J4[🖼️ Imagen<br/>png, jpg · sin probar]
        J5[(Catálogo EODHD<br/>92.257 fondos)]
        J6[(📑 Folletos)]
        J7[(📈 Histórico diario)]
    end

    subgraph UNI[Un único modelo para todo]
        direction TB
        U1[Oír · entender · preguntar · decidir criterios · elegir y repartir<br/>Gemma 3n E2B en GPU<br/>alternativa: Gemma 3n E4B o Gemini]
        U2[Búsqueda semántica en folletos<br/>MiniLM multilingüe en CPU]
        U3[Filtrar el catálogo, caídas y grupos de fondos parecidos<br/>sin modelo]
        U1 -- criterios --> U2 --> U3
        U3 -- una línea por grupo --> U1
    end

    subgraph VOZ2[De texto a voz · Gemma 3n no genera voz]
        direction TB
        V1[Redactar lo que se va a decir<br/>plantillas con las cifras de los datos<br/>las preguntas de asesor las escribe Gemma 3n]
        V2[Texto a voz<br/>es-ES-ElviraNeural con edge-tts, en línea<br/>respaldo: Piper es_ES-davefx-medium, local en CPU]
        V1 --> V2
    end

    subgraph OUT2[Salidas]
        direction TB
        P1[🔊 Audio WAV que suena solo<br/>en el navegador]
        P2[📄 Informe PDF con gráficos<br/>ReportLab, sin modelo]
        P3[🔊 Audio resumen descargable]
        P4[🖥️ Tabla, perfil editable y avisos en pantalla]
    end

    J1 --> U1
    J2 --> U1
    J3 --> U1
    J4 --> U1
    J5 --> U3
    J6 --> U2
    J6 --> U3
    J7 --> U3
    U1 -- preguntas, fondos y pesos --> V1
    V2 --> P1
    V2 --> P3
    U1 --> P2
    U1 --> P4
    J7 -- evolución real y escenarios --> P2
```

### Cómo se crea la voz

1. **Las métricas del resumen proceden del código y los datos.** Las preguntas obligatorias («¿durante cuántos años…?») y el resumen final son plantillas con número de fondos, rentabilidad y caída de la cartera y lo que ganó un fondo comparable. Gemma 3n redacta las preguntas de asesor en Modelo único. Separar cálculo y generación reduce el riesgo de inventar cifras, pero no acredita la exactitud de los datos de origen ni de todo texto generado.
2. **Un modelo de texto a voz lo convierte en audio.** Por defecto, la voz neuronal `es-ES-ElviraNeural`, a la que se llama por internet con el paquete `edge-tts` (servicio de voz de Microsoft, no oficial): se le envía el texto y devuelve un MP3, que se convierte a WAV. Si no hay conexión, el paquete no está o se pone `VOICE=local`, lo hace Piper con la voz `es_ES-davefx-medium`, un modelo pequeño que corre en la CPU del equipo.
3. **El navegador lo reproduce.** En manos libres suena solo y, al acabar, el micrófono vuelve a escuchar. El resumen final se puede además descargar.

La frase que el modelo de lenguaje escribe sobre la cartera aparece en el PDF, no se lee en voz alta. El código está en `src/tts.py`.

Las dos versiones comparten datos, filtros, validación, voz de respuesta e informe. Lo que cambia es quién oye, entiende, pregunta y decide: cuatro piezas especializadas en una, un solo modelo en la otra.

## Cómo funciona

```mermaid
flowchart LR
    U[Voz por micrófono<br/>o texto] --> S[Voz a texto]
    S --> E[Extraer preferencias]
    E --> F{¿Falta plazo,<br/>riesgo o divisa?}
    F -- sí --> Q[Pregunta hablada] --> U
    F -- no --> A[Preguntas de asesor:<br/>objetivo, experiencia, caídas]
    F -- no, en segundo plano --> C[El modelo decide<br/>los criterios]
    C --> R[El código los aplica<br/>a todo el catálogo]
    D[(92.257 fondos)] --> R
    K[(Folletos: riesgo oficial,<br/>costes, mínimos)] --> R
    R --> G[Histórico diario: caídas<br/>y grupos de fondos parecidos]
    H[(Precios diarios)] --> G
    A --> L[El modelo elige y reparte<br/>una línea por grupo]
    G --> L
    L --> T[Resumen hablado breve<br/>y detalle si se pide]
    L --> P[Informe PDF con gráficos]
```

1. **Conversación.** Son obligatorios el plazo (de 1 a 30 años), el riesgo y la divisa. Los fondos se comparan con las cifras del catálogo a 1, 3 o 5 años, la ventana más cercana al plazo; el comportamiento de la cartera se calcula con el histórico diario de todo el plazo que exista. Lo que falte se pregunta por voz. Importe, zona, sector, clase de activo y grado de diversificación son opcionales.
2. **Preguntas de asesor.** Una vez, y se pueden saltar: objetivo (crecer, conservar, rentas), experiencia y reacción ante una caída del 20 %. Si las respuestas no sostienen el riesgo declarado, se baja un nivel y se explica.
3. **El modelo decide los criterios.** A partir de la conversación transcrita fija cuánto pesan el ajuste al riesgo, el Sharpe y la rentabilidad, la volatilidad objetivo, una rentabilidad mínima y, si el cliente pidió un tema («oro», «tecnología»), las palabras que deben aparecer en el nombre del fondo. Las palabras genéricas («fondo», «crecimiento», «diversificado») se descartan, y los fondos cuyo folleto es afín al tema pasan ese filtro aunque no lleven la palabra en el nombre.
4. **El código los aplica a todo el catálogo.** Siempre se descartan los fondos de otra divisa, sin datos recientes o por encima de la volatilidad máxima del perfil (bajo 10 %, medio 20 %, alto 35 %): el modelo no puede subir el riesgo. Una ficha verificada que contradiga la preferencia no se sustituye por una coincidencia en el nombre. Se agrupan las posibles clases de participación por nombre, conservando números de índices y términos de cobertura; esta agrupación es aproximada.
5. **El modelo elige y reparte.** Tras los filtros quedan hasta 2.000 candidatos. Con el histórico diario se agrupan los que se mueven muy parecido (correlación semanal superior a 0,9) y el modelo lee una línea por grupo, la del mejor fondo, con su caída máxima; las caídas mayores de lo que tolera el perfil (10 %, 25 % y 45 %; un 30 % menos si el cliente dijo que vendería) restan puntuación: 150 líneas representan a muchos más fondos (1.600 en una prueba sin tema concreto). Si la conversación da tiempo, el modelo criba además los grupos siguientes por lotes de 100 y sus elegidos entran en la lista final. Devuelve qué fondos y con qué peso. Se respeta un número concreto solicitado de 1 a 7 fondos; «un solo fondo» recibe el 100 %. Si no se indica, se eligen entre 2 y 7 según la diversificación. Sin el histórico diario, el modelo lee los 150 mejores candidatos.
6. **Validación.** Solo se aceptan fondos de la lista y pesos numéricos finitos. Tanto el modelo como las reglas respetan un mínimo del 5 % y un máximo del 60 % por fondo (80 % si hay dos; 100 % si solo hay uno). Si el modelo falla o su reparto no es válido, deciden las reglas, que además no eligen dos fondos del mismo grupo. Sin histórico diario reparten por inversa de la volatilidad, o dan más peso a los fondos que mejor encajan si el objetivo es crecer.
7. **Segunda mirada con el histórico diario.** Si dos fondos elegidos se mueven casi igual (correlación semanal superior a 0,95), el peor colocado se sustituye por el siguiente candidato. Cuando deciden las reglas y hay histórico, el reparto es por paridad de riesgo con las correlaciones reales.
8. **Entrega.** La página resume la cartera de viva voz en menos de un minuto, en lenguaje llano y sin nombres ni pesos: cuántos fondos, de qué tipo, cuánto habría ganado y cuánto llegó a caer en conjunto. Lo pone en contexto: dice cuánto ganó un fondo comparable típico y, si los elegidos están entre los que mejor lo hicieron, avisa de que no hay que contar con que se repita. Después pregunta si se quiere el detalle y, solo entonces, lee fondo a fondo. En pantalla y en el PDF están siempre la conversación, el perfil, los criterios, la cartera y el porqué de cada fondo, con el porcentaje de fondos comparables al que superó; la evolución real que habría tenido la cartera, con su volatilidad y su caída máxima; y, en otro gráfico, tres escenarios para el plazo pedido: su peor año, un fondo comparable típico y su mejor año. Los importes se asignan a céntimos conservando el total y los límites de concentración.

Se reconocen importes en EUR, USD, GBP y CHF, con cifras o expresados en español («diez mil euros», «10.000 dólares», «ciento veinte euros con cincuenta céntimos»). Los importes negativos, nulos o no interpretables que se detecten requieren aclaración; no se transforman en cantidades positivas. Cuando se pregunta por el importe, se puede contestar solo con la cantidad. El importe sigue siendo opcional si no se ha indicado.

El paso 3 y las 150 líneas del paso 5 necesitan el filtro en GPU (o Claude). Con Gemma 3 1B en CPU no hay paso 3 y el modelo elige entre 10 líneas.

### Límites que conviene conocer

- **Las cifras nunca salen del modelo.** Rentabilidades, volatilidades y motivos por fondo vienen del catálogo, de los folletos y del histórico diario.
- **El modelo no lee los 92.257 fondos uno a uno.** No caben en su contexto: decide los criterios, el código los aplica a todos y el modelo elige entre una línea por grupo de fondos parecidos. La página dice cuántos fondos ha tenido en cuenta. La criba por lotes solo ocurre si la conversación deja tiempo; en una charla de tres turnos no llega a empezar.
- **Zona y sector solo están verificados donde hay folleto.** Para el resto, las preferencias se comprueban con el nombre del fondo y el informe lo marca como «exposición no verificada».
- **La inversión mínima solo se conoce donde hay ficha** (unos 1.700 fondos); esos se descartan si el mínimo supera el importe. Para el resto, por debajo de 100.000 se prefiere, entre las clases de un mismo fondo, la que no parece institucional; el mínimo real hay que mirarlo en el folleto.
- **Las exclusiones por sector no se pueden garantizar** sin la composición completa; la app lo dice y pregunta si sigue sin ellas.
- **El reparto no es una optimización de cartera completa.** Con el histórico diario se usan correlaciones para evitar duplicados y para la paridad de riesgo, pero no hay objetivo de rentabilidad esperada ni frontera eficiente.
- **La selección mira al pasado.** El modelo tiende a elegir los fondos que más subieron: en una prueba con riesgo alto propuso cinco fondos que habían superado a más del 97 % de los 30.768 comparables, cuando la mediana de estos fue del +11,8 % en cinco años. El informe y el resumen lo dicen expresamente, pero la selección en sí no se ha corregido.
- **Los escenarios son una ilustración, no una previsión.** Repetir todos los años el peor o el mejor es muy improbable. El escenario central usa lo que ganó un fondo comparable típico, no el año mediano de la cartera.
- **Los plazos largos se comparan con cifras a 5 años.** El catálogo no trae rentabilidad, volatilidad ni Sharpe a 10 años. Del histórico diario salen las caídas, los grupos y el comportamiento de la cartera, no esas tres cifras.
- **Los modelos locales no consultan internet.** Solo usan lo que se les pasa.
- **En manos libres no se puede interrumpir a la página:** solo escucha cuando ha terminado de hablar.

## Folletos de los fondos

`scripts/procesar_folletos.py` convierte la documentación descargada (carpeta `folletos/` con su `indice.csv`) en una fila por fondo, en `data/private/folletos.csv`:

| Documento | Qué se extrae |
| --- | --- |
| DFI de la CNMV y KID (PRIIPs) | Riesgo oficial de 1 a 7, periodo recomendado, costes corrientes, categoría y objetivo |
| Ficha de Deutsche Bank | Inversión mínima, divisa y gastos corrientes |
| Folleto resumido de la SEC (497K) | Objetivo y gastos anuales |

Zona, sector y clase de activo se deducen del objetivo con palabras clave. Se hace con reglas, sin modelo: son miles de documentos y tarda alrededor de un minuto. En la primera pasada (17.000 documentos de 19.128 fondos) se obtuvo el riesgo oficial de 2.406 fondos, los costes de 14.419 y la inversión mínima de 1.686.

Cómo se usa en la recomendación:

- **Riesgo oficial:** se descarta el fondo si su clase de riesgo supera la del perfil (bajo hasta 3, medio hasta 4, alto hasta 6), aunque su volatilidad pasada quepa.
- **Inversión mínima:** se descarta si supera el importe que se quiere invertir.
- **Costes:** restan puntuación y se muestran al modelo, que los tiene en cuenta al elegir.
- **Zona, sector y activos:** lo que dice el folleto cuenta como exposición verificada.
- **Fondos que solo están en los folletos:** no tienen precios en el catálogo, así que no se pueden puntuar. Los que encajan por divisa, riesgo oficial y preferencias se listan aparte en la página y en el PDF.

La descarga sigue creciendo: el script solo lee los fondos nuevos o con documentos nuevos, e `iniciar.bat` lo ejecuta en cada arranque.

**Búsqueda semántica.** Al procesar los folletos se calcula un vector del objetivo de cada fondo con un modelo de embeddings multilingüe pequeño, en CPU (unos 5 minutos la primera vez para 17.467 fondos; después solo los nuevos). Cuando el cliente pide un tema, se buscan los fondos cuyo objetivo se le parece aunque la palabra no esté en el nombre ni el folleto esté en español: «oro y metales preciosos» encuentra fondos de «gold». Esos fondos pasan el filtro de palabras que fija el modelo y reciben un pequeño extra de puntuación. Los filtros fijos de zona, sector y clase de activo no cambian.

Los folletos no se leen con un modelo de lenguaje ni con OCR: un documento escaneado o con una redacción distinta de la habitual se queda sin datos.

## Histórico diario de precios

La app usa `fondos_diarios.parquet` (317 millones de filas, 5,3 GB, no incluido en el repositorio) si está en la carpeta del proyecto, en `data/private`, en `..\datos` o en la ruta de la variable `DAILY_PARQUET`. Solo lee los fondos que necesita:

- **Antes de elegir:** los precios semanales de hasta 2.000 candidatos (3–5 s). De ahí salen la caída máxima de cada fondo, que cuenta en el ranking, y los grupos de fondos que se mueven muy parecido, que permiten al modelo leer una línea por grupo.
- **Después de elegir:** sustituye fondos casi idénticos, reparte por paridad de riesgo cuando deciden las reglas y calcula la evolución real, la volatilidad conjunta, la caída máxima y los escenarios del informe.

Sin el Parquet, el modelo lee los 150 mejores candidatos y el informe muestra la simulación ilustrativa.

Los fondos que solo tienen folleto siguen sin poder puntuarse: el Parquet contiene los mismos fondos que el catálogo.

## Comparación entre versiones

| | Especialistas | Modelo único |
| --- | --- | --- |
| Voz a texto | Whisper `large-v3-turbo` (GPU) o `small` (CPU) | Gemma 3n E2B |
| Entender la petición | Reglas en español (Gemma 3 4B opcional) | Gemma 3n E2B |
| Qué preguntar | Preguntas fijas | Fijas para los datos obligatorios; Gemma 3n redacta las de asesor |
| Criterios, elección y reparto | Gemma 3 4B | Gemma 3n E2B |
| Hablar | Voz neuronal en línea o Piper | La misma (Gemma 3n no genera voz) |
| Memoria de GPU | unos 6 GB (Gemma 3 4B en 4 bits y Whisper) | 11 GB |

Las dos comparten catálogo, filtros, validación, PDF y voz. La comparación cambia tanto los modelos como parte de la orquestación, por lo que no es un experimento que aísle una única variable. Cada respuesta muestra los segundos que ha tardado. El gestor mantiene un modelo Gemma a la vez en GPU; Whisper se carga por separado. Al cambiar de versión puede ser necesario recargar Gemma.

**Primera comparación.** Es una sola conversación de tres turnos hablados, con voz sintética y un micrófono simulado en el navegador; no es una evaluación.

- **Especialistas:** transcribió y extrajo bien los datos y entregó la propuesta en el tercer turno. Las preguntas tardan 1–3 s; la propuesta, unos 11 s tras conversar por voz.
- **Modelo único:** transcribió bien casi todo, pero no dedujo la divisa de «10.000 euros» (hubo que decírsela en un turno más) e inventó datos que nadie había dicho, como una zona «global» y «un solo fondo», con lo que acabó proponiendo un único fondo. Cada turno tarda entre 14 y 32 s. Sus preguntas suenan más naturales.

## Modelos candidatos por paso

En negrita, las integraciones previstas por el código y los instaladores, no una certificación de que estén disponibles en cualquier equipo. Las alternativas no se han probado aquí ni se afirma que sean superiores; hay que verificar sus requisitos y disponibilidad antes de sustituir un modelo.

| Paso | Integración actual | Alternativa local | Alternativa en la nube |
| --- | --- | --- | --- |
| Voz a texto | **Whisper `large-v3-turbo`** (GPU) · **Whisper `small`** (CPU) | NVIDIA Parakeet TDT v3 | `gpt-4o-transcribe` |
| Búsqueda semántica en folletos | **`paraphrase-multilingual-MiniLM-L12-v2`** (CPU, con fastembed) | `bge-m3`; `multilingual-e5-large` | Embeddings por API |
| Extraer preferencias | **Reglas en español** · opcional **Gemma 3 4B** (GPU) | Gemma 3 12B; Qwen 2.5 7B | Claude Haiku 4.5; Gemini Flash |
| Criterios, elección y reparto | **Gemma 3 4B en 4 bits** (GPU, 4 GB) · respaldo **Gemma 3 1B Q4** (CPU) | Gemma 3 12B; Qwen 2.5 14B | Claude Opus 5.5 (preparado, deshabilitado) |
| Texto a voz | **Voz neuronal `es-ES-ElviraNeural`** (en línea) · respaldo **Piper `es_ES-davefx-medium`** (CPU) | Kokoro; XTTS-v2 | ElevenLabs Multilingual; `gpt-4o-mini-tts` |
| Modelo único multimodal | **Gemma 3n E2B** (GPU, 11 GB) | Gemma 3n E4B; Phi-4 multimodal; Qwen2.5-Omni | Gemini; GPT-4o audio |
| Leer folletos, DFI y KID | **Reglas sobre el texto del PDF** (PyMuPDF, sin modelo) | Docling; Qwen2.5-VL para escaneados | Claude con PDF |

Para cambiar el Whisper de CPU, poner `WHISPER_MODEL=medium` en `.env` y ejecutar la descarga desde PowerShell con la misma variable: `$env:WHISPER_MODEL = "medium"`, seguido de `.\.venv\Scripts\python scripts\download_models.py`. El script de descarga no carga `.env` por sí solo.

Whisper, ante silencio o ruido, escribe frases que aprendió de vídeos subtitulados («Subtítulos por la comunidad de Amara.org», «¡Suscríbete!»). La app las descarta y, en manos libres, sigue escuchando sin decir nada.

### Claude y consulta web (deshabilitado)

El filtro también puede hacerlo Claude por API. Está preparado pero **no se ha probado**, porque no hay clave configurada. Para activarlo: `pip install -r requirements-claude.txt`, copiar `.env.example` a `.env` y poner `ANTHROPIC_API_KEY`; entonces aparece «Claude por API» en la barra lateral. Con `ADVISOR_WEB=on` Claude puede además buscar en la web datos públicos de los candidatos (categoría, zona, comisiones). Consume tokens de pago y envía al proveedor la conversación y la lista de candidatos; `.env` está ignorado por Git.

## Estructura

```text
instalar.bat, iniciar.bat  Instalación y arranque con doble clic
instalar_parte2_opcional.bat  Modelos de GPU, opcional
index.html                 Portada con los enlaces a la aplicación
app.py                     Punto de entrada y navegación
paginas/                   Especialistas, Modelo único, Pruebas y estado
estilo.css, .streamlit/    Aspecto y configuración de la página
src/conversation.py        Diálogo: qué falta, qué preguntar, ajuste de riesgo
src/preferences.py         Reglas de extracción en español
src/audio.py               Voz a texto (Whisper)
src/tts.py                 Texto a voz (voz neuronal en línea y Piper)
src/extraction.py          Extracción de preferencias con modelo de lenguaje
componentes/manos_libres/  Micrófono manos libres (HTML y JavaScript)
src/recommender.py         Filtros, puntuación, clases de un mismo fondo
src/ai_filter.py           Criterios, selección y reparto con IA (Gemma o Claude)
src/omni.py                Lo mismo con Gemma 3n como único modelo
src/hf_model.py            Carga de modelos en la GPU, uno a la vez
src/report.py              Informe PDF y texto del resumen hablado
src/ui.py                  Piezas de interfaz comunes a las dos versiones
scripts/download_models.py Descarga de modelos desde Hugging Face
scripts/import_catalog.py  Conversión del Markdown EODHD a CSV
scripts/procesar_folletos.py  Lectura de DFI, KID y fichas a una fila por fondo
src/brochures.py           Uso de esa documentación en la recomendación
src/semantic.py            Búsqueda semántica sobre los objetivos de los folletos
src/history.py             Histórico diario: caídas, grupos de fondos parecidos, paridad de riesgo, evolución y escenarios
src/screening.py           Trabajo en segundo plano durante la conversación y una línea por grupo de fondos
src/money.py               Importes en español y reparto al céntimo
data/demo_funds.csv        Catálogo sintético
data/private/, models/     Catálogo real y modelos, ignorados por Git
tests/                     Pruebas (python -m unittest discover -s tests)
docs/                      Pitch (pitch.md y pitch_fondoclaro_v3.pptx) y capturas
requirements.txt           Dependencias de la instalación básica
requirements-gpu.txt       Dependencias de los modelos de GPU
requirements-claude.txt    Solo si se activa Claude por API
```

El dataset EODHD y sus derechos de uso no se incluyen en el repositorio; por cuestiones de la licencia. Gemma se distribuye bajo los términos de uso de Google y Piper (`piper-tts`) bajo GPL-3.0.
