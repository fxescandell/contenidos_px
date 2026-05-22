# Prompt técnico 1 — Arquitectura e implementación base

Actúa como un arquitecto de software senior y desarrollador principal especializado en Python, FastAPI, procesamiento documental, OCR, automatización editorial y WordPress.

Quiero que diseñes e implementes una aplicación técnica real, robusta y mantenible para automatizar la creación y actualización de contenido en un único sitio WordPress a partir de archivos que llegan a una carpeta caliente.

## 1. OBJETIVO TÉCNICO
La aplicación debe ejecutarse como un servicio externo en Docker y hacer esto:

1. vigilar una carpeta caliente ubicada en un Synology
2. detectar nuevos lotes de contenido
3. copiar esos lotes a una zona interna de trabajo
4. calcular hashes para evitar reprocesados
5. agrupar archivos por artículo candidato
6. extraer texto de PDF, DOCX e imágenes
7. aplicar OCR cuando haga falta
8. clasificar municipio, categoría y subtipo
9. redactar o ampliar contenido cuando sea necesario, sin inventar datos
10. optimizar imágenes
11. construir la estructura final del artículo
12. mapear el contenido al formato WordPress requerido
13. generar JSON compatible con un sistema de importación existente
14. dejar el contenido listo para importar
15. marcar como pendiente de revisión cuando haya dudas
16. enviar avisos por Telegram
17. permitir reprocesado manual o automático si cambia el lote

La prioridad es:
- robustez
- claridad del código
- trazabilidad
- facilidad de mantenimiento
- bajo acoplamiento
- capacidad de ampliar reglas por categoría

No quiero una app SaaS multiusuario.
No quiero una solución genérica para miles de clientes.
Quiero una solución específica para un único WordPress.

## 2. CONTEXTO FUNCIONAL
El sitio WordPress trabaja con varios CPT separados por tipo de contenido.
La taxonomía de municipio está compartida entre todos los CPT.

Municipios principales:
- Cerdanya
- Maresme
- Berguedà
- General

Categorías/CPT:
- agenda
- noticies
- esports
- turisme actiu
- nens i joves
- cultura
- gastronomia
- consells
- entrevistes

Casos especiales:
- cultura tiene dos variantes internas: cultura general y libros
- gastronomia tiene dos variantes internas: gastronomía general y receta
- agenda tiene campos más sensibles y debe validarse mejor
- algunos contenidos solo llegan como cartel en imagen
- algunos contenidos llegan como carpeta con DOCX + imágenes
- algunos contenidos llegan como PDF individual
- en una fase futura quiero poder procesar un PDF completo de revista y separarlo automáticamente en artículos independientes

## 3. RESTRICCIONES IMPORTANTES
- No inventar datos jamás.
- El sistema puede mejorar redacción, ordenar texto y ampliarlo un poco, pero no puede inventar fechas, nombres, lugares ni hechos.
- No confiar en el nombre del archivo para evitar duplicados.
- La detección de duplicados debe hacerse por hash de archivo y hash de lote.
- Si el contenido ya fue procesado y no ha cambiado, no debe reprocesarse.
- Si el lote cambió, debe poder reprocesarse.
- Si hay dudas, el estado final debe ser "pending review" o equivalente.
- La imagen destacada es obligatoria.
- Si no hay imagen destacada posible, es un error crítico.
- La V1 debe generar JSON compatible con un importador existente.
- La publicación directa a WordPress debe diseñarse como extensión futura, no como dependencia obligatoria de la V1.

## 4. ENTRADAS SOPORTADAS
La aplicación debe soportar:
- carpetas
- subcarpetas
- PDF digital
- PDF escaneado
- DOCX
- JPG
- PNG

Escenarios reales:
- carpeta raíz como "cerdanya 320"
- subcarpetas por categoría
- carpetas por artículo
- archivos mezclados dentro de carpetas generales
- DOCX con contenido y varias imágenes asociadas
- cartel único del que hay que extraer texto por OCR
- PDF individual de un artículo
- futuro: PDF completo de revista

## 5. ESTRATEGIA GENERAL
Implementa arquitectura modular por capas.

Debes separar claramente:
- configuración
- base de datos
- modelos
- servicios de ingesta
- extracción documental
- OCR
- clasificación
- redacción/editorial
- procesado de imágenes
- adaptadores WordPress
- generación de JSON
- notificaciones
- panel mínimo
- tareas de reprocesado

La app debe ser fácil de entender y fácil de modificar.

## 6. STACK TÉCNICO OBLIGATORIO
Usa:
- Python 3.12
- FastAPI
- SQLAlchemy 2.x
- Alembic
- Pydantic v2
- PostgreSQL preferiblemente, aunque SQLite puede admitirse para desarrollo local
- watchdog
- Pillow
- python-docx
- PyMuPDF o pdfplumber
- Tesseract OCR o PaddleOCR
- httpx
- Jinja2 para panel simple
- Docker
- docker-compose

Opcional pero recomendado:
- Celery o RQ en V2 si realmente aporta valor
- Redis solo si es necesario
- structlog o logging estándar bien configurado

## 7. ESTRUCTURA DE PROYECTO
Quiero una estructura parecida a esta:

app/
  api/
    routes/
    dependencies/
  core/
    logging.py
    security.py
    utils.py
  config/
    settings.py
  db/
    base.py
    session.py
    models/
    repositories/
    migrations/
  schemas/
  services/
    watcher/
    ingestion/
    grouping/
    extraction/
    ocr/
    classification/
    editorial/
    images/
    wordpress/
    import_json/
    telegram/
  adapters/
    agenda.py
    noticies.py
    esports.py
    turisme_actiu.py
    nens_i_joves.py
    cultura.py
    gastronomia.py
    consells.py
    entrevistes.py
  templates/
  static/
  tests/
  main.py

Explícame si propones una variante mejor, pero mantén el código organizado y modular.

## 8. MODELO DE DATOS
Diseña un modelo de datos real con SQLAlchemy y Alembic.

Debes proponer e implementar tablas como mínimo para:
1. source_batches
2. source_files
3. content_candidates
4. extracted_documents
5. processed_images
6. editorial_outputs
7. wordpress_exports
8. processing_events

[Implementa estos modelos con campos detallados, índices y restricciones razonables.]

## 9. CONFIGURACIÓN
Implementa configuración por variables de entorno con Pydantic Settings.

Debes incluir:
- APP_ENV
- APP_DEBUG
- DATABASE_URL
- HOT_FOLDER_PATH
- WORKING_FOLDER_PATH
- IMPORT_OUTPUT_PATH
- OCR_ENGINE
- OCR_LANGUAGE
- MAX_IMAGE_WIDTH
- JPEG_QUALITY
- TELEGRAM_BOT_TOKEN
- TELEGRAM_CHAT_ID
- LLM_PROVIDER
- LLM_API_BASE
- LLM_API_KEY
- LLM_MODEL
- AUTO_PUBLISH_CONFIDENCE_THRESHOLD
- AUTO_REVIEW_CONFIDENCE_THRESHOLD

Crea:
- .env.example
- validación de settings
- valores por defecto sensatos
- separación dev/prod si procede

## 10. PIPELINE DE PROCESAMIENTO
Implementa un pipeline claro y desacoplado.

Fases:
A. detect_batch()
B. scan_files()
C. group_candidates()
D. extract_content()
E. classify_candidate()
F. process_images()
G. build_editorial_output()
H. adapt_to_wordpress()
I. export_output()
J. finalize_status()

[Desarrolla cada fase con código real, contratos claros y manejo de errores serio.]

## 11. CLASIFICACIÓN HÍBRIDA
Implementa una capa híbrida:
1. reglas deterministas
2. clasificador heurístico
3. LLM como respaldo

La clasificación debe devolver un objeto con:
- municipality
- category
- subtype
- confidence
- signals
- reasoning_summary

Nunca uses solo el LLM como única fuente de decisión.

## 12. EXTRACCIÓN Y OCR
Implementa componentes separados:
- PdfTextExtractor
- PdfOcrExtractor
- DocxExtractor
- ImageOcrExtractor

Cada extractor debe devolver:
- raw_text
- cleaned_text
- metadata
- extraction_confidence
- extraction_method

## 13. CAPA EDITORIAL
Quiero un servicio editorial que reciba:
- texto extraído
- categoría detectada
- subtipo
- imágenes disponibles
- metadatos detectados

y devuelva:
- título final
- resumen
- contenido final en HTML
- campos estructurados
- observaciones
- warnings

## 14. ADAPTERS WORDPRESS
Implementa una capa de adaptadores por CPT, con una clase base común y adaptadores concretos.

## 15. FORMATO DE EXPORTACIÓN
La V1 debe exportar JSON compatible con un importador existente.
Diseña una capa de exportación desacoplada.

## 16. PANEL WEB MÍNIMO
Implementa un panel mínimo con FastAPI + Jinja2.

## 17. TELEGRAM
Implementa un servicio simple de Telegram.

## 18. LOGGING Y AUDITORÍA
Implementa logging consistente y eventos en base de datos.

## 19. TESTS
Incluye tests reales mínimos con pytest.

## 20. README
Genera un README muy detallado.

## 21. ORDEN DE ENTREGA
Quiero que construyas el proyecto por bloques completos y reales.

## 22. ESTILO DE CÓDIGO
- código claro
- muy legible
- funciones pequeñas
- nombres largos y descriptivos
- typing completo
- pocos atajos
- nada de pseudocódigo si ya puedes implementar código real

## 23. ENTREGABLE INICIAL
Empieza entregando:
1. propuesta final de estructura del proyecto
2. modelos de base de datos completos
3. settings y .env.example
4. pipeline base
5. clases abstractas principales
6. adapters base
7. export builder base
8. README inicial
9. Dockerfile
10. docker-compose.yml

Recuerda:
- no inventar datos
- priorizar revisión si hay duda
- featured image obligatoria
- JSON en V1
- WordPress directo en V2
- PDF completo de revista en V3
