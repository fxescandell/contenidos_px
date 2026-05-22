# Prompt técnico 3 — Extracción, OCR, clasificación híbrida y scoring de confianza

Actúa como un arquitecto de software senior y especialista en procesamiento documental, OCR, NLP, clasificación híbrida, diseño de heurísticas y automatización editorial con Python.

Quiero que implementes la capa de extracción, OCR, agrupación documental, clasificación híbrida y cálculo de confianza para una aplicación que transforma archivos entrantes en artículos listos para WordPress.

En esta fase NO quiero centrarme en UI, panel avanzado ni integración profunda con WordPress. Quiero el núcleo inteligente que decide qué es cada contenido, qué texto se puede confiar y cuándo algo debe ir a revisión.

## 1. OBJETIVO DE ESTA FASE
Debes implementar, con código real y modular:

1. detección y lectura de archivos de un lote
2. agrupación de archivos por artículo candidato
3. extracción de texto desde PDF digital
4. OCR desde PDF escaneado e imágenes
5. lectura estructurada de DOCX
6. limpieza y normalización del texto extraído
7. clasificación híbrida de municipio, categoría y subtipo
8. cálculo explícito de scores de confianza
9. detección de contradicciones y ambigüedades
10. decisión automática entre:
   - continuar
   - dejar en revisión
   - marcar error crítico

No quiero un clasificador opaco.
Quiero que cada decisión deje rastros, señales y explicaciones auditables.

## 2. CONTEXTO DEL NEGOCIO
Los contenidos llegan desde una carpeta caliente y suelen venir con esta estructura:

- carpeta raíz tipo "cerdanya 320"
- subcarpetas por categoría: agenda, cultura, gastronomia, etc.
- a veces una carpeta por artículo
- a veces un DOCX o PDF con varias imágenes asociadas
- a veces un solo cartel en JPG o PNG
- a veces una carpeta genérica con muchas imágenes mezcladas

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
- cultura puede ser cultura general o libro
- gastronomia puede ser genérico o receta
- agenda requiere mucha precisión con fechas
- consells tiene un patrón diferente
- algunos carteles no contienen suficiente información, pero igualmente debe generarse una pieza mínima útil sin inventar datos

## 3. RESTRICCIONES CRÍTICAS
- No inventar datos.
- No confiar solo en nombres de archivo.
- No confiar solo en el LLM.
- No usar OCR como única estrategia si el PDF ya tiene texto digital.
- Si el contenido es ambiguo o contradictorio, debe quedar pendiente de revisión.
- Si una agenda no tiene una fecha mínimamente válida, no puede ir automática.
- Las decisiones deben producir señales, scores y motivos.

## 4. ARQUITECTURA DE ESTA CAPA
Quiero módulos claramente separados:

app/services/
  grouping/
  extraction/
  ocr/
  text_cleaning/
  classification/
  scoring/
  signals/
  confidence/
  validation/

Y reglas en:

app/rules/
  municipality_rules.py
  category_rules.py
  subtype_rules.py
  agenda_rules.py
  contradiction_rules.py
  grouping_rules.py

## 5. AGRUPACIÓN DOCUMENTAL
Implementa una capa de grouping robusta.

### Objetivo
A partir de un lote con muchos archivos, generar candidatos a artículo.

### Input
- batch metadata
- lista de source files con ruta, tamaño, hash, extensión, mime, nombre relativo

### Output
- list[GroupingResult]

### Reglas de agrupación
Orden de prioridad:
1. si hay carpeta propia por artículo, esa carpeta manda
2. si hay un DOCX/PDF principal y varias imágenes en la misma carpeta, se agrupan
3. si las imágenes comparten prefijo razonable con el documento principal, sube la confianza
4. si las imágenes solo están cerca en orden o ubicación, confianza media
5. si hay imágenes sueltas en carpeta genérica sin relación clara, no forzar agrupación fuerte
6. si un único cartel aparece solo, crear un candidato individual

### Señales de agrupación
Quiero señales explícitas como:
- same_folder
- dedicated_article_folder
- document_plus_images
- filename_prefix_similarity
- shared_stem_tokens
- image_count_nearby
- isolated_poster_candidate
- weak_unstructured_group

### Scoring de agrupación
Devuelve:
- grouping_confidence 0.0 - 1.0
- grouping_strategy enum
- signals
- warnings

## 6. EXTRACCIÓN DOCUMENTAL
Implementa extractores separados y especializados.

### Clases obligatorias
- BaseExtractor
- PdfDigitalExtractor
- PdfScannedExtractor
- DocxStructuredExtractor
- ImagePosterExtractor
- CompositeCandidateExtractor

### Reglas
- si un PDF tiene texto digital suficiente, usar extracción nativa
- si un PDF casi no tiene texto digital, aplicar OCR
- DOCX debe leer párrafos, títulos y, si es posible, estilos relevantes
- imagen debe pasar por OCR
- el extractor compuesto debe combinar resultados de varios archivos del candidato

### Cada extractor debe devolver
- raw_text
- cleaned_text
- extracted_blocks
- metadata
- extraction_method
- extraction_confidence
- warnings
- errors

## 7. LIMPIEZA Y NORMALIZACIÓN DE TEXTO
Implementa una capa de limpieza seria.

Debe hacer:
- colapsar espacios duplicados
- limpiar saltos de línea absurdos
- corregir fragmentación típica de OCR
- detectar líneas repetidas
- limpiar caracteres basura comunes
- conservar estructura si hay encabezados útiles
- producir:
  - raw_text
  - normalized_text
  - reading_text

Quiero clases como:
- OcrTextCleaner
- PdfTextCleaner
- GeneralTextNormalizer

## 8. BLOQUES Y ESTRUCTURA DETECTADA
Además del texto plano, quiero detección de bloques.

Detecta si es posible:
- títulos probables
- subtítulos
- párrafos
- líneas con fecha/hora
- líneas con lugar
- listas de actividades
- datos editoriales de libro
- datos tipo receta

Devuelve algo como:
- detected_title_candidates
- detected_datetime_lines
- detected_location_lines
- detected_activity_blocks
- detected_book_fields
- detected_recipe_fields
- detected_keyword_spans

## 9. CLASIFICACIÓN HÍBRIDA
Implementa una clasificación híbrida por etapas.

### Etapa 1: reglas duras por carpeta
- municipio por carpeta raíz
- categoría por subcarpeta

### Etapa 2: señales documentales
- patrones del contenido
- palabras clave
- estructuras detectadas
- fechas
- nombres propios
- vocabulario típico por sección

### Etapa 3: subtipo
- cultura general vs libro
- gastronomía general vs receta
- agenda general vs agenda con actividades

### Etapa 4: respaldo LLM opcional
- solo si la confianza heurística no es suficiente
- nunca como única fuente
- el LLM debe recibir señales y texto resumido, no archivos completos sin control
- la salida del LLM debe validarse contra reglas y no puede imponerse sola

## 10. OBJETO DE DECISIÓN DE CLASIFICACIÓN
Quiero un objeto muy claro como:

ClassificationDecision:
- municipality
- municipality_confidence
- category
- category_confidence
- subtype
- subtype_confidence
- overall_confidence
- confidence_band
- signals
- contradictions
- review_reasons
- reasoning_summary
- llm_used
- llm_supported_fields

## 11. SEÑALES DE CLASIFICACIÓN
Diseña un catálogo estable de señales.

Ejemplos:
- municipality_from_root_folder
- municipality_from_batch_name
- municipality_from_content_keywords
- category_from_subfolder
- category_from_agenda_keywords
- category_from_interview_structure
- category_from_recipe_structure
- category_from_book_metadata
- category_from_sports_keywords
- subtype_book_detected
- subtype_recipe_detected
- subtype_agenda_activity_blocks_detected
- contradiction_folder_vs_content
- contradiction_multiple_municipalities
- contradiction_multiple_categories
- low_text_quality
- weak_ocr_result

Cada señal debe tener:
- code
- source
- weight
- message
- evidence

## 12. REGLAS POR CATEGORÍA
Implementa rulesets concretos.

### Agenda
Señales fuertes:
- fechas
- horas
- ubicaciones
- palabras tipo: agenda, activitats, programa, dissabte, diumenge, entrada, inscripció
- estructura de listado

### Entrevistes
Señales fuertes:
- formato pregunta/respuesta
- nombre de persona destacada
- uso de comillas o estructura periodística

### Cultura libro
Señales fuertes:
- autor
- editorial
- any edició
- títol del llibre
- referencias claras a libro, novel·la, assaig, lectura

### Gastronomía receta
Señales fuertes:
- ingredients
- elaboració
- passos
- quantitats
- temps de cocció

### Esports
Señales fuertes:
- competición
- torneo
- equipo
- marcador
- campeonato

### Nens i joves
Señales fuertes:
- escuela
- infants
- joves
- educació
- activitats familiars

### Consells
Señales fuertes:
- tono explicativo breve
- sección consejo
- ámbitos como salud, mascotas, hogar, etc.

### Turisme actiu
Señales fuertes:
- rutas
- excursión
- desnivel
- acceso
- itinerari
- refugio

## 13. SUBTIPOS
Implementa detectores de subtipo:

- CulturaBookSubtypeDetector
- GastronomyRecipeSubtypeDetector
- AgendaActivitiesSubtypeDetector

Cada detector debe devolver:
- subtype
- confidence
- signals
- extracted_structured_data

## 14. EXTRACCIÓN DE FECHAS Y HORAS
Implementa un módulo específico para agenda.

Quiero:
- DatePatternExtractor
- DateRangeExtractor
- SearchDatesBuilder
- AgendaFieldResolver

Debe poder detectar:
- fecha única
- rango de fechas
- varias fechas
- etiquetas de hora
- fechas útiles para buscador

Devuelve estructura canónica como:
- event_date
- start_date
- end_date
- search_dates
- raw_datetime_labels

Si no puede construir una fecha mínimamente fiable:
- agenda debe quedar en revisión

## 15. CONTRADICCIONES
Implementa una capa explícita para contradicciones.

Ejemplos:
- carpeta dice agenda, contenido parece entrevista
- carpeta dice maresme, contenido menciona claramente Cerdanya como núcleo principal
- dos categorías compiten con señales parecidas
- OCR pésimo pero decisión demasiado fuerte

Quiero:
- ContradictionDetector
- contradiction list con severidad
- impacto en score final

## 16. SCORING Y BANDAS DE CONFIANZA
No quiero un único número mágico sin explicación.

Implementa:
- score por agrupación
- score por extracción
- score por municipio
- score por categoría
- score por subtipo
- score global

Y bandas:
- VERY_HIGH
- HIGH
- MEDIUM
- LOW
- VERY_LOW

Reglas sugeridas:
- >= 0.90 muy alta
- >= 0.75 alta
- >= 0.55 media
- >= 0.35 baja
- < 0.35 muy baja

Además, aplica penalizaciones por:
- contradicciones
- OCR pobre
- falta de señales fuertes
- agrupación débil

## 17. DECISIÓN OPERATIVA FINAL
Implementa una función final tipo:
- decide_candidate_next_step()

Debe devolver:
- CONTINUE_AUTOMATIC
- CONTINUE_WITH_REVIEW
- BLOCK_AND_REVIEW
- FAIL

Reglas:
- agenda sin fecha fiable -> BLOCK_AND_REVIEW
- featured image imposible -> BLOCK_AND_REVIEW o FAIL según configuración
- confianza alta y sin contradicciones -> CONTINUE_AUTOMATIC
- confianza media -> CONTINUE_WITH_REVIEW
- confianza baja -> BLOCK_AND_REVIEW

## 18. LLM BACKUP STRATEGY
Diseña una interfaz LLM pero con uso controlado.

Quiero:
- BaseClassificationAssistant
- LlmClassificationAssistant
- NoopClassificationAssistant

El LLM solo puede:
- sugerir categoría
- sugerir subtipo
- resumir evidencias
- ordenar campos extraídos

El LLM no puede:
- inventar datos
- sobreescribir una contradicción fuerte sin justificación
- convertir un caso débil en automático solo por su opinión

## 19. RESULTADOS OPERACIONALES
Quiero schemas claros para:
- GroupingResult
- ExtractionResult
- CompositeExtractionResult
- SignalEvidence
- ContradictionItem
- ClassificationDecision
- ConfidenceScoreBreakdown
- CandidateOperationalDecision

## 20. TESTS
Incluye tests reales para:
- agrupación por carpeta dedicada
- agrupación débil en carpeta genérica
- PDF digital con extracción nativa
- PDF sin texto que activa OCR
- OCR de cartel
- detección de libro
- detección de receta
- detección de agenda con fechas
- contradicción carpeta agenda vs entrevista
- penalización por OCR pobre
- decisión final de revisión

## 21. README DE ESTA CAPA
Genera un README técnico que explique:
- cómo funciona la agrupación
- cómo se elige extractor
- cómo se calculan señales
- cómo funciona el score
- qué manda más: carpeta, contenido o LLM
- cuándo se bloquea algo
- cómo extender reglas por categoría

## 22. ORDEN DE ENTREGA
Quiero que entregues el trabajo en este orden:
1. estructura de módulos de esta capa
2. enums y schemas operacionales
3. grouping service
4. extractores
5. cleaners
6. detectors por categoría y subtipo
7. contradiction detector
8. scoring engine
9. decision engine
10. tests
11. README

## 23. ESTILO DE IMPLEMENTACIÓN
- código muy legible
- typing completo
- funciones pequeñas
- nombres descriptivos
- separación clara entre reglas, señales y scoring
- sin if/else monstruosos
- sin lógica mágica oculta
- con docstrings solo donde aporten valor

## 24. ENTREGABLE MÍNIMO DE LA RESPUESTA
Empieza devolviendo código real para:
- schemas operacionales
- enums de señales, contradicciones y bandas de confianza
- GroupingService
- extractores base y concretos
- text cleaners
- RuleBasedClassificationService
- subtype detectors
- contradiction detector
- scoring engine
- decision engine
- tests mínimos
- README técnico inicial

Recuerda:
- no inventar datos
- el LLM es apoyo, no juez supremo
- si hay contradicción seria, revisión
- agenda requiere rigor adicional
- todo debe dejar trazabilidad auditable
