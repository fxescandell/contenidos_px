# WordPress Editorial Automation - Fase 2 (Extracción y Clasificación Híbrida)

Esta fase implementa el motor documental de la aplicación: lectura de archivos, agrupación, extracción de texto y toma de decisiones sobre clasificación y confianza, sin inventar datos y enviando a revisión casos dudosos.

## Flujo Documental

1. **Agrupación (`services/grouping/orchestrator.py`)**
   El orquestador toma una lista de archivos que acaban de entrar por la carpeta caliente y los agrupa en *Candidatos a Artículo* usando diferentes estrategias. Por defecto, si vienen agrupados en subcarpetas, se usa la `FolderGroupingStrategy`.
   
2. **Extracción y Limpieza (`services/extraction/orchestrator.py` & `cleaning.py`)**
   Cada archivo de un grupo se procesa con su extractor correspondiente (PDF, DOCX, OCR para Imágenes).
   - El texto extraído pasa inmediatamente por un `TextCleaningPipeline` que normaliza espacios, junta párrafos rotos (típicos en PDFs escaneados) y elimina ruido sin destruir la estructura original.

3. **Detección de Señales (`services/classification/signals/detectors.py`)**
   El texto limpio es escaneado por una batería de detectores (ej. `AgendaPatternDetector`, `RecipePatternDetector`). Estos detectores no toman decisiones finales, solo emiten `DetectedSignal` (evidencias con un peso determinado).

4. **Clasificación Híbrida (`services/classification/classifiers.py`)**
   Con las pistas que venían de las carpetas originales (`batch_hints`) y las señales del texto (`signals`), clasificamos:
   - **Municipio** (`MunicipalityClassifier`): Detecta conflictos si la carpeta dice "Maresme" pero el texto menciona constantemente "Cerdanya".
   - **Categoría** (`CategoryClassifier`): Usa la estructura detectada (ej. si hay señales de ingredientes, es Gastronomía).
   - **Subtipo** (`SubtypeClassifier`): Refina la categoría (ej. Gastronomía -> Receta).

5. **Scoring de Confianza y Revisión (`services/classification/scoring.py`)**
   - El `ConfidenceScorer` calcula una puntuación ponderada y asigna una banda (VERY_HIGH, HIGH, MEDIUM, LOW, VERY_LOW).
   - El `ReviewDecisionService` decide si el artículo puede continuar en el pipeline automático o debe pararse. **Cualquier conflicto, confianza menor a HIGH o extracción pobre envía el artículo a `REQUIRES_REVIEW`**.

6. **Orquestación Final (`services/classification/orchestrator.py`)**
   El `ClassificationOrchestrator` es la fachada principal que coordina todo el proceso 3, 4 y 5, devolviendo un objeto `FinalClassificationResult` listo para ser convertido en un `CanonicalContent` en la siguiente fase.

## ¿Dónde entra el LLM?
En esta fase he dejado preparado el campo `llm_used` en los esquemas. La filosofía del proyecto dicta que el LLM **solo apoya** y no debe sobreescribir señales estructurales fuertes. Se implementará como un detector o estrategia de respaldo adicional cuando la confianza híbrida (Reglas + Señales) sea media o baja.

## Cómo ampliar
- Para detectar un nuevo tipo de artículo (ej. Entrevistas):
  1. Crea un `InterviewPatternDetector` en `signals/detectors.py` que busque patrones de Pregunta/Respuesta ("P:", "R:", "?").
  2. Añádelo al `FeatureExtractionOrchestrator`.
  3. Ajusta `CategoryClassifier` para que reaccione a esa señal y devuelva `ContentCategory.ENTREVISTES`.
