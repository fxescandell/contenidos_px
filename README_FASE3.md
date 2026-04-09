# WordPress Editorial Automation - Fase 3 (Pipeline End-to-End)

Esta fase implementa la integración completa de los componentes construidos en las fases anteriores, creando el orquestador principal del proceso, el sistema de vigilancia de carpetas y el servicio de ingestión de archivos.

## Componentes Principales

### 1. Watcher (`services/watcher/service.py`)
Utiliza la librería `watchdog` para monitorizar de forma pasiva la carpeta caliente (hot folder) alojada en el Synology o unidad montada.
- Ignora archivos ocultos o de sistema (ej. `.DS_Store`).
- Implementa un pequeño retraso (delay) al detectar un evento `on_created` para asegurarse de que el archivo grande o la carpeta se ha terminado de copiar antes de lanzar el pipeline.

### 2. Ingestión (`services/ingestion/service.py`)
Se encarga de mover de forma segura los archivos desde el volumen externo a una carpeta interna de trabajo temporal (`working_directory`).
- Si entra un archivo suelto, lo copia.
- Si entra una carpeta entera, la recorre recursivamente recreando su estructura internamente.
- Calcula el `hash sha256` de cada archivo y de todo el lote combinado. Esto sirve para evitar el reprocesamiento de duplicados en la base de datos.
- Extrae la extensión, tamaño y adivina el `mime_type`.

### 3. Pipeline Orchestrator (`services/pipeline/orchestrator.py`)
El gran director de orquesta. Es la función que llama el Watcher cuando detecta contenido.
- **Paso 1: Ingestión.** Llama al `IngestionService` y persiste el `SourceBatch` en la BD. Si detecta un duplicado (por hash), aborta el proceso con un `Warning`.
- **Paso 2: Grouping.** Llama al `GroupingOrchestrator` de la Fase 2 para separar el lote en "Candidatos a Artículo".
- **Paso 3-4: Extracción.** Lee el texto de los documentos e imágenes del grupo.
- **Paso 5: Clasificación.** Cruza los textos con las pistas de las carpetas para determinar Municipio, Categoría y Subtipo.
- **Paso 6: Procesado de Imágenes.** Copia y prepara las imágenes (mockeado en `ImageProcessingService` a la espera de integraciones finales).
- **Paso 7: Editorial Builder.** Genera el contenido base y extrae los `structured_fields_json` neutros.
- **Paso 8: Canonical Content.** Persiste el resultado intermedio y neutral en BD (`CanonicalContent`).
- **Paso 9: Adapters y Validación.** Usa el `AdapterFactory` para instanciar el adaptador correcto (ej. `AgendaWordPressAdapter`), valida el contenido y si falla, lo envía al estado de `REVIEW_REQUIRED`.
- **Paso 10: Exportación.** Llama al `WordPressJsonExportBuilder` para generar el JSON final que se enviará al importador de WordPress.

### 4. Event Logger (`services/pipeline/events.py`)
Toda la traza de lo que ocurre (desde que se ingesta el lote hasta que se exporta, incluyendo advertencias o errores críticos) se guarda en la tabla `processing_events`. Esto permite una auditoría perfecta y construir un Panel de Control en la Fase 4.

## Manejo de Estados
La máquina de estados definida en `app/core/states.py` se aplica estrictamente:
- Los Lotes (`SourceBatch`) pasan por: `DETECTED` -> `PROCESSING` -> `FINISHED` / `FAILED` / `REVIEW_REQUIRED`.
- Los Candidatos (`ContentCandidate`) pasan por: `CREATED` -> `EXPORTED` / `REVIEW_REQUIRED` / `FAILED`.

Si **cualquier candidato** de un lote requiere revisión, todo el lote queda marcado como `REVIEW_REQUIRED` en su estado superior, para que el editor humano lo revise en bloque.

## Pruebas (Tests)
Puedes correr las pruebas completas usando:
```bash
source venv/bin/activate
python -m pytest tests/
```
Se han añadido pruebas específicas para la ingestión y la correcta captura de eventos del Watcher en `tests/test_phase3.py`.
