# Prompt técnico 2 — Modelo de datos, schemas, adapters y pipeline interno

Actúa como un arquitecto de software principal y desarrollador senior especializado en Python, FastAPI, SQLAlchemy, OCR, procesamiento documental, automatización editorial y WordPress.

Quiero que diseñes e implementes la base técnica completa de una aplicación editorial automatizada para un único sitio WordPress. En esta fase NO quiero que te centres en el frontend bonito, sino en el corazón estable del sistema:

- modelo de datos
- contracts internos
- schemas
- adapters WordPress
- pipeline interno
- validaciones
- reglas
- persistencia
- control de estados
- exportación JSON
- trazabilidad

Quiero una base muy sólida, extensible y fácil de mantener.

## 1. OBJETIVO DE ESTA FASE
Quiero que implementes la parte más estable de la aplicación:
1. modelo de base de datos completo
2. schemas Pydantic de entrada/salida
3. entidades internas del pipeline
4. abstracciones base
5. adapters por CPT de WordPress
6. validadores por categoría
7. capa de exportación JSON
8. repositorios
9. servicios base del pipeline
10. sistema de estados
11. trazabilidad y auditoría
12. pruebas mínimas de las piezas críticas

## 2. CONTEXTO REAL DEL PROYECTO
La app procesa contenido editorial que entra en una carpeta caliente y acaba convertido en contenido listo para WordPress.

El sitio WordPress tiene varios CPT separados por categoría editorial.

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

Municipios principales:
- Cerdanya
- Maresme
- Berguedà
- General

Reglas conocidas:
- normalmente cada artículo pertenece a una sola categoría/CPT
- normalmente pertenece a un solo municipio
- en casos ambiguos puede usarse General
- featured_image es obligatoria
- si faltan datos críticos, no se publica automáticamente
- si hay dudas, debe quedar pendiente de revisión

Casos especiales muy importantes:
- cultura tiene subtipo “libro” dentro del mismo CPT
- gastronomia tiene subtipo “recepta” dentro del mismo CPT
- agenda tiene campos estructurados más sensibles
- consells usa un esquema de clasificación de municipio diferente al resto

## 3. DATOS REALES A RESPETAR
Diseña la arquitectura teniendo en cuenta estas realidades de los exports WordPress:

A. CAMPOS BASE COMUNES
La mayoría de CPT comparten campos base como:
- post_title
- post_content
- post_excerpt
- post_date
- post_name
- post_author
- post_status
- featured_image
- post_format
- comment_status
- ping_status
- article-destacat
- muchos campos SEO/meta vacíos o repetidos

B. MUNICIPIOS EN LA MAYORÍA DE CPT
Muchos CPT usan campos del tipo:
- municipi-maresme
- municipi-cerdanya
- municipi-bergueda
- municipi-bages
- municipi-solsones
- municipi-pirineus
- disctricte-barcelona

C. AGENDA
Agenda tiene además:
- tipus-d-article
- categoria-d-agenda
- data-esdeveniment
- data-inici
- data-final
- dates-que-es-realitza-buscador
- titol-activitat
- data-i-hora-activitat
- on-es-realitza-l-activitat
- descripcio-activitat
- informacio-adicional
- imatge-activitat
- activitats

D. CULTURA
Cultura puede usar:
- tipus-d-article = "Llibre secció Cultura"
- titol-del-llibre
- autor-a-del-llibre
- any-edicio
- editorial
- patrocinat-per
- pagina-del-patrocinador
- disposem-de-pdf-de-lectura-previa
- pdf-llegir-un-fragment

E. GASTRONOMIA
Gastronomía usa:
- tipus-article-gastronomia = "Recepta" o "Géneric"

F. CONSELLS
Consells usa:
- consell
- municipi-consells

Debes construir una arquitectura que no dependa de campos hardcodeados en todas partes.
Quiero una solución con adapters y mapeos declarativos.

## 4. REQUISITO PRINCIPAL DE DISEÑO
Quiero una arquitectura basada en una representación interna neutral del contenido.

Eso significa:
- el extractor NO debe hablar el lenguaje WordPress
- el clasificador NO debe construir JSON de WordPress
- el generador editorial NO debe conocer nombres reales de custom fields
- los nombres exactos de los campos WordPress deben resolverse en la capa adapter

Debes separar:
1. Internal Canonical Model
2. Validation Layer
3. Adapter Layer
4. Export Layer

## 5. MODELO CANÓNICO INTERNO
Diseña una representación interna única para cualquier contenido.

Debe existir una entidad central tipo CanonicalContentItem con esta idea:
- source_batch_id
- source_candidate_id
- municipality
- category
- subtype
- source_title
- detected_title
- final_title
- source_summary
- final_summary
- source_body_text
- final_body_html
- language
- featured_image_candidate_id
- image_items
- structured_fields
- keyword_signals
- extraction_confidence
- grouping_confidence
- classification_confidence
- editorial_confidence
- requires_review
- review_reasons
- errors
- warnings
- metadata
- timestamps

Quiero que esta entidad exista tanto:
- como schema Pydantic
- como resultado estable del pipeline
- como objeto que los adapters consumen

Diseña subestructuras internas como:
- CanonicalImageItem
- CanonicalEventDate
- CanonicalActivityItem
- CanonicalBookData
- CanonicalRecipeData
- CanonicalMunicipalityAssignment
- CanonicalClassificationDecision
- CanonicalValidationResult

## 6. DOMINIO Y ENUMS
Define enums y tipos fuertemente tipados para evitar cadenas sueltas.

Quiero enums como mínimo para:
- Municipality
- ContentCategory
- ContentSubtype
- ProcessingStatus
- ReviewReason
- ExtractionMethod
- ExportFormat
- ImageRole
- ConfidenceBand
- ValidationSeverity
- SourceFileRole
- CandidateGroupingStrategy

## 7. BASE DE DATOS
Diseña e implementa modelos SQLAlchemy 2.x y migración Alembic inicial.

Quiero tablas robustas y normalizadas, incluyendo:
- source_batches
- source_files
- content_candidates
- candidate_source_files
- extracted_documents
- candidate_images
- canonical_contents
- validation_reports
- wordpress_exports
- processing_events
- reprocessing_requests

[Implementa estos modelos con UUID, relaciones, índices, unique constraints y relaciones completas.]

## 8. PERSISTENCIA Y REPOSITORIOS
Quiero una capa de repositorios limpia, no queries desperdigadas por todo el proyecto.

Implementa repositorios separados como:
- SourceBatchRepository
- SourceFileRepository
- ContentCandidateRepository
- ExtractedDocumentRepository
- CanonicalContentRepository
- ValidationReportRepository
- WordPressExportRepository
- ProcessingEventRepository
- ReprocessingRequestRepository

## 9. SCHEMAS PYDANTIC
Define schemas Pydantic v2 muy claros para:
A. INPUT / INTERNAL
B. API / VIEW
C. OPERATIONAL

Usa:
- field validators
- model validators
- tipos explícitos
- enums
- defaults sensatos

## 10. CONTRATOS INTERNOS ENTRE MÓDULOS
Diseña interfaces claras entre módulos.

Quiero contratos explícitos como:
- GroupingService
- ExtractionService
- ClassificationService
- ImageProcessingService
- EditorialBuilderService
- ValidationService
- WordPressAdapter
- ExportBuilder

No quiero acoplamiento implícito ni diccionarios caóticos sin schema.

## 11. SISTEMA DE ESTADOS
Implementa una máquina de estados simple pero seria.

Estados del batch:
- DETECTED
- COPYING
- COPIED
- SCANNED
- GROUPED
- PROCESSING
- FINISHED
- FAILED
- REVIEW_REQUIRED

Estados del candidate:
- CREATED
- GROUPED
- EXTRACTED
- CLASSIFIED
- EDITORIAL_BUILT
- VALIDATED
- EXPORTED
- READY
- REVIEW_REQUIRED
- FAILED

Estados del export:
- PENDING
- BUILT
- WRITTEN
- FAILED

## 12. VALIDACIÓN
La validación debe existir en dos niveles:
A. VALIDACIÓN CANÓNICA GENERAL
B. VALIDACIÓN ESPECÍFICA POR CPT

Quiero:
- códigos de error estables
- severity = INFO / WARNING / ERROR / CRITICAL
- ValidationResult con:
  - issues
  - is_valid
  - requires_review
  - blocking_errors_count

## 13. ADAPTER LAYER
Implementa una capa real de adapters WordPress, no solo if/else.

Quiero una clase abstracta base y adaptadores concretos:
- AgendaWordPressAdapter
- NoticiesWordPressAdapter
- EsportsWordPressAdapter
- TurismeActiuWordPressAdapter
- NensIJovesWordPressAdapter
- CulturaWordPressAdapter
- GastronomiaWordPressAdapter
- ConsellsWordPressAdapter
- EntrevistesWordPressAdapter

## 14. MAPEO DE MUNICIPIOS
No hardcodees municipio en todos los adapters.
Crea un servicio o estrategia de mapping reusable y testeable.

## 15. STRUCTURED_FIELDS CANÓNICOS
La parte más importante: define structured_fields internos antes del adapter.

Quiero nombres internos limpios en inglés y luego mapping al naming WordPress real solo en adapter.

## 16. EXPORT BUILDER
Implementa una capa de exportación separada:
- BaseExportBuilder
- WordPressJsonExportBuilder

Debe soportar exportación por artículo y por lote desde diseño.

## 17. CONTENT BUILDER / EDITORIAL RESULT
Quiero ya el contrato estable de EditorialBuildResult.

## 18. IMAGE MODELING
Modela bien las imágenes desde la base.

## 19. REVIEW MODEL
Quiero que la revisión quede bien modelada desde el principio.

## 20. REPROCESADO
Diseña desde ya el reprocesado, con ReprocessingScope y reglas de invalidación.

## 21. CLASES ABSTRACTAS
Implementa abstracciones reales para que el sistema quede limpio.

## 22. PATRÓN DE REGLAS
Quiero que las reglas no estén repartidas en if gigantes.
Diseña rulesets o policies.

## 23. ESTRUCTURA DE CARPETAS DEL PROYECTO
Mantén una estructura muy clara por capas.

## 24. PRUEBAS
Incluye tests reales con pytest para mapping, validación, exportación, adapters y transiciones de estado.

## 25. README TÉCNICO DE ESTA FASE
Genera un README muy detallado centrado en esta capa técnica.

## 26. ESTILO DE IMPLEMENTACIÓN
- Python moderno
- typing completo
- funciones pequeñas
- nombres muy descriptivos
- nada de código críptico
- nada de lógica escondida en utilidades genéricas absurdas

## 27. ORDEN DE ENTREGA
Quiero que entregues el trabajo por este orden exacto:
1. árbol final del proyecto
2. enums, estados y tipos base
3. settings y .env.example
4. modelos SQLAlchemy
5. migración Alembic inicial
6. repositorios
7. schemas Pydantic
8. abstracciones base
9. rulesets y policies
10. validation layer
11. adapters WordPress
12. export builder
13. tests
14. README técnico

## 28. ENTREGABLE MÍNIMO DE ESTA RESPUESTA
Empieza devolviendo directamente código real para:
- enums.py
- states.py
- settings.py
- modelos SQLAlchemy completos
- schemas Pydantic principales
- BaseWordPressAdapter
- AgendaWordPressAdapter
- CulturaWordPressAdapter
- GastronomiaWordPressAdapter
- ConsellsWordPressAdapter
- BaseExportBuilder
- WordPressJsonExportBuilder
- ValidationResult y validators principales
- tests mínimos
- README técnico inicial

Recuerda:
- no inventar datos
- featured_image obligatoria
- si hay duda -> review
- canonical model neutral
- adapters desacoplados
- structured_fields internos primero
- WordPress naming solo al final
