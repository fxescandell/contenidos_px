# WordPress Editorial Automation - Fase 1 (Base Técnica)

Esta es la base técnica de la aplicación editorial automatizada para WordPress.

## Propósito de la Fase 1
El objetivo de esta fase es construir una base estable, robusta y escalable que defina claramente el modelo de datos, los flujos internos y la separación de responsabilidades antes de añadir la lógica compleja de IA y extracción documental.

## Arquitectura y Capas

### 1. Modelo Canónico (`CanonicalContentItem`)
El corazón del sistema. Es una representación neutral del artículo, independiente de WordPress. Ningún extractor ni clasificador debe saber qué es un "custom field" de WordPress; solo deben saber rellenar el modelo canónico.

### 2. Capa de Validación (`app/services/validation/`)
Se asegura de que el contenido canónico es válido para ser exportado. Comprueba tanto reglas genéricas (por ejemplo, que el artículo tenga título e imagen destacada) como reglas específicas de cada categoría (ej. Agenda requiere fechas, Recetas requieren un subtipo específico).

### 3. Capa de Adaptadores (`app/adapters/`)
Es el único lugar del proyecto que "habla el idioma" de WordPress. 
Cada CPT (Custom Post Type) de WordPress tiene su propio Adapter (ej. `AgendaWordPressAdapter`, `CulturaWordPressAdapter`). 
Los adapters toman el modelo canónico y lo mapean a los campos específicos (`tipus-d-article`, `data-esdeveniment`, etc.).

### 4. Capa de Exportación (`app/services/export/`)
Toma el resultado del Adapter y lo convierte en el payload final (JSON) que consumirá el importador actual de WordPress.

### 5. `structured_fields` Internos
Para mantener el modelo canónico neutral, los datos estructurados extraídos de los documentos (ej. detalles de un libro, fechas de un evento) se guardan en el campo `structured_fields_json` usando nombres limpios en inglés (ej. `book_title`, `event_date`). Luego, los Adapters se encargan de traducir `book_title` a `titol-del-llibre`.

## Cómo ampliar el sistema

- **Añadir un nuevo CPT:**
  1. Añadirlo al enum `ContentCategory` en `app/core/enums.py`.
  2. Crear un nuevo adapter en `app/adapters/nuevo_cpt.py` heredando de `BaseWordPressAdapter`.
  3. Implementar el método `build_meta_fields` en el nuevo adapter.

- **Añadir nuevas reglas de validación:**
  1. Modificar `CanonicalValidationService` en `app/services/validation/service.py` para añadir las reglas del CPT correspondiente.

- **Modificar la lógica de Municipios:**
  1. Editar `app/rules/municipalities.py`.

## Modelos de Base de Datos y Repositorios
La persistencia está definida en `app/db/models.py` usando SQLAlchemy 2.0 con anotaciones de tipo (`Mapped`). 
El acceso a base de datos se debe hacer siempre a través de los repositorios definidos en `app/db/repositories/`.

## Tests
Los tests se pueden ejecutar con `pytest tests/`. Prueban la lógica crítica de mapeo, validación y adaptadores.
