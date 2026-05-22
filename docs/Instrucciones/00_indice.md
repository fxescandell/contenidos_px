# Carpeta de prompts y roadmap para la app de automatización editorial WordPress

## Archivos incluidos

### 01_prompt_maestro_codex.txt
Prompt general de producto y arquitectura.
Úsalo para explicarle a Codex la visión global del proyecto.

### 02_prompt_tecnico_arquitectura.txt
Prompt técnico centrado en arquitectura general, stack, pipeline y módulos.
Úsalo después del prompt maestro o como punto de partida técnico.

### 03_prompt_tecnico_datos_adapters_pipeline.txt
Prompt técnico centrado en la parte más estable:
- modelo de datos
- schemas
- canonical model
- adapters
- validaciones
- exportación

Es el mejor prompt para empezar a construir el proyecto de verdad.

### 04_prompt_tecnico_extraccion_ocr_clasificacion.txt
Prompt técnico para:
- grouping
- extracción documental
- OCR
- señales
- clasificación híbrida
- scoring de confianza
- review reasons

Úsalo después de tener bien cerrada la base de datos y los adapters.

### 05_roadmap_y_walkthrough.md
Roadmap completo y walkthrough operativo:
- orden de construcción
- qué revisar en cada fase
- checklist técnico
- flujo recomendado de trabajo con Codex

## Orden recomendado de uso

1. 03_prompt_tecnico_datos_adapters_pipeline.txt
2. 04_prompt_tecnico_extraccion_ocr_clasificacion.txt
3. 02_prompt_tecnico_arquitectura.txt si quieres reforzar contexto global
4. 01_prompt_maestro_codex.txt como referencia general
5. 05_roadmap_y_walkthrough.md como guía continua
