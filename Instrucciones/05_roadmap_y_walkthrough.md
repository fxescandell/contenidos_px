# Roadmap y walkthrough para construir la aplicación de automatización editorial WordPress

## Objetivo
Tener una referencia única para construir, revisar y poner en marcha la aplicación sin perder el orden. Este documento sirve como guía práctica para trabajar con Codex por fases y también como checklist técnico del proyecto.

---

## Visión general del sistema

La aplicación final debe:

- vigilar una carpeta caliente en Synology
- detectar nuevos lotes de archivos
- copiarlos a una zona de trabajo
- calcular hashes para evitar duplicados
- agrupar archivos por artículo
- extraer texto de DOCX, PDF digital, PDF escaneado e imágenes
- aplicar OCR cuando haga falta
- clasificar municipio, categoría y subtipo
- redactar o ampliar el contenido sin inventar datos
- optimizar imágenes
- construir el contenido final
- mapearlo al formato WordPress real
- generar JSON compatible con el importador actual
- dejar el artículo listo para importar, revisar o publicar
- notificar por Telegram
- permitir reprocesado

---

## Principios de diseño que no hay que romper

1. WordPress es el destino, no el cerebro.
2. La app debe vivir fuera de WordPress, en Docker.
3. La representación interna del contenido debe ser neutral.
4. Los nombres reales de campos WordPress solo deben aparecer en los adapters.
5. Nunca inventar fechas, nombres, lugares o hechos.
6. Si hay duda, mandar a revisión.
7. La imagen destacada es obligatoria.
8. Los duplicados se controlan con hash, no con nombre de archivo.
9. La V1 genera JSON. La publicación directa puede venir después.

---

## Arquitectura final recomendada

### Capa 1. Ingesta
Responsable de detectar lotes nuevos y copiarlos a una carpeta de trabajo.

### Capa 2. Persistencia
Base de datos para lotes, archivos, candidatos, extracciones, contenidos canónicos, validaciones, exportaciones y eventos.

### Capa 3. Grouping
Agrupa archivos en candidatos a artículo.

### Capa 4. Extracción documental
Lee DOCX, PDF y OCR de imágenes o PDFs escaneados.

### Capa 5. Clasificación híbrida
Usa reglas, señales y LLM para decidir municipio, categoría y subtipo.

### Capa 6. Modelo canónico
Representación neutral del artículo ya clasificado.

### Capa 7. Validación
Valida que el contenido tiene lo mínimo para seguir.

### Capa 8. Editorial
Ordena, amplía y estructura el contenido final sin inventar datos.

### Capa 9. Imágenes
Optimiza, ordena y decide destacada, inline o galería.

### Capa 10. Adapter WordPress
Convierte el contenido canónico al formato exacto del CPT correspondiente.

### Capa 11. Exportación
Genera el JSON final para el importador.

### Capa 12. Revisión y notificaciones
Panel mínimo, Telegram y reprocesado.

---

## Orden correcto de construcción

### Fase 0. Preparación y análisis
Antes de programar:

- revisar todos los JSON exportados del WordPress
- sacar una tabla real de CPT y campos obligatorios
- confirmar el formato final del JSON de importación
- decidir dónde se montará el volumen del Synology
- decidir estructura ideal de carpetas de entrada
- definir variables de entorno

### Entregables de Fase 0
- mapa de CPT
- mapa de municipios
- lista de campos obligatorios por sección
- convenciones de carpetas
- ejemplo de lote de prueba

---

## Fase 1. Núcleo estable del proyecto

### Objetivo
Construir la base que no debería cambiar mucho.

### Qué incluye
- estructura de proyecto
- settings
- enums
- estados
- modelos SQLAlchemy
- migración Alembic inicial
- repositorios
- schemas Pydantic
- canonical model
- validation layer base
- adapters WordPress
- export builder JSON
- tests mínimos de estas piezas
- Docker base

### Resultado esperado
Una aplicación que ya sabe representar correctamente:
- lotes
- archivos
- candidatos
- contenido canónico
- validaciones
- exportaciones

### Qué revisar al terminar
- que cada tabla tenga sentido
- que los estados estén bien definidos
- que el canonical model sea neutral
- que los adapters no contengan lógica mezclada con extracción
- que agenda, cultura, gastronomía y consells estén modelados correctamente

---

## Fase 2. Extracción documental y clasificación híbrida

### Objetivo
Conseguir que la app entienda lo que entra.

### Qué incluye
- grouping strategies
- extractores DOCX
- extractores PDF digital
- OCR para imagen y PDF escaneado
- limpieza de texto
- detectores de señales
- clasificadores de municipio, categoría y subtipo
- orquestador de clasificación
- scoring de confianza
- decisión de review

### Resultado esperado
Dado un lote de prueba, la app debe poder decir:
- qué archivos forman un artículo
- qué municipio tiene
- qué categoría/CPT es
- qué subtipo usa
- con qué confianza
- si necesita revisión

### Qué revisar al terminar
- que el nombre de carpeta sea una pista, no una verdad absoluta
- que la IA no mande sola
- que agenda, libro y receta se detecten bien
- que el OCR malo penalice confianza
- que los conflictos de señales se guarden

---

## Fase 3. Construcción editorial

### Objetivo
Convertir texto extraído en contenido utilizable.

### Qué incluye
- builder editorial neutral
- generación de título final
- resumen final
- cuerpo HTML final
- inserción básica de imágenes
- estructura de campos canónicos
- reglas de ampliación segura

### Resultado esperado
Cada artículo candidato debe terminar con:
- título usable
- resumen usable
- contenido HTML usable
- structured_fields completos
- warnings y errores documentados

### Qué revisar al terminar
- que no se inventen datos
- que si el texto es bueno se respete
- que el cartel único genere un contenido breve pero correcto
- que la agenda tenga fechas claras
- que la imagen destacada siempre exista

---

## Fase 4. Procesado de imágenes

### Objetivo
Automatizar lo que ahora haces a mano.

### Qué incluye
- redimensionado a 2000 px
- JPG calidad 60
- conversión PNG a JPG opcional
- preparación futura para WebP
- selección de destacada
- selección inline o galería
- asociación contextual básica

### Resultado esperado
Cada candidato tendrá:
- imágenes optimizadas
- destacada definida
- orden de uso claro
- referencias listas para exportación

### Qué revisar al terminar
- que no se pierdan originales
- que los tamaños sean correctos
- que la destacada sea coherente
- que no se usen imágenes dudosas como destacada

---

## Fase 5. Exportación JSON e integración con WordPress

### Objetivo
Generar salida real compatible con tu plugin actual.

### Qué incluye
- WordPressJsonExportBuilder
- escritura de JSON por artículo
- escritura opcional por lote
- checksum de exportación
- logs de exportación
- pruebas con tu plugin real

### Resultado esperado
Un JSON listo para importar con:
- campos base
- custom fields
- taxonomías o campos de municipio
- featured image
- contenido final
- estado correcto

### Qué revisar al terminar
- que el importador acepte el JSON
- que respete las relaciones esperadas
- que los campos especiales de agenda, libros y recetas entren bien
- que consells use sus claves especiales correctas

---

## Fase 6. Watcher y pipeline end-to-end

### Objetivo
Hacer que todo el flujo funcione automático de punta a punta.

### Qué incluye
- watcher de carpeta
- detección de lotes
- pipeline coordinado
- guardado de eventos
- reintentos básicos
- estados finales

### Resultado esperado
Al dejar un lote nuevo en la carpeta caliente:
- se detecta
- se copia
- se procesa
- se clasifica
- se exporta
- se notifica

### Qué revisar al terminar
- que no procese dos veces el mismo lote
- que el hash funcione bien
- que los errores no dejen la base en estado inconsistente
- que el proceso pueda reanudarse

---

## Fase 7. Panel mínimo y revisión manual

### Objetivo
Darte una forma sencilla de revisar lo dudoso.

### Qué incluye
- lista de lotes
- lista de candidatos
- vista de texto extraído
- vista de clasificación
- vista del JSON generado
- marcar aprobado
- marcar revisión
- reprocesar

### Resultado esperado
Poder resolver los casos dudosos sin tocar la base de datos ni editar a mano archivos internos.

### Qué revisar al terminar
- que sea sencillo
- que no intente ser un gran dashboard
- que muestre lo importante
- que permita relanzar solo una parte si hace falta

---

## Fase 8. Telegram

### Objetivo
Recibir avisos útiles y no ruido.

### Eventos mínimos
- lote nuevo detectado
- lote procesado correctamente
- error crítico
- candidato pendiente de revisión
- fallo OCR
- fallo exportación

### Qué revisar
- que los mensajes sean claros
- que incluyan nombre de lote y candidato
- que indiquen acción sugerida

---

## Fase 9. Reprocesado serio

### Objetivo
No rehacerlo todo siempre y poder corregir por partes.

### Alcances mínimos
- reprocesar extracción
- reprocesar clasificación
- reprocesar editorial
- reprocesar export
- full rebuild

### Qué revisar
- que invalidar una fase posterior tenga sentido
- que no borre trabajo válido innecesariamente
- que quede auditado quién y por qué lo relanzó

---

## Fase 10. Mejoras de precisión

### Objetivo
Subir la calidad después de que la base ya funcione.

### Mejores siguientes pasos
- asociación más fina de imágenes a bloques internos
- mejores detectores de entrevista y noticias
- reglas específicas por revista
- reglas específicas por municipio
- mejor tratamiento de PDFs muy sucios
- mejor scoring de OCR

---

## Fase 11. Modo revista completa

### Objetivo
Procesar el PDF entero de una revista y separarlo en artículos.

### Qué incluye
- segmentación por páginas
- detección de inicio y fin de artículo
- extracción por bloque editorial
- clasificación por artículo segmentado
- asociación de imágenes internas si existen

### Nota importante
Esta fase es compleja y no debe meterse antes de que la V1 simple funcione bien.

---

# Walkthrough práctico para trabajar con Codex

## Paso 1. Pedir la base técnica
Usa primero:
- `03_prompt_tecnico_datos_adapters_pipeline.txt`

### Qué tiene que devolverte bien
- modelos SQLAlchemy
- schemas Pydantic
- adapters
- export builder
- validation layer

### Qué debes revisar
- que agenda tenga sus campos
- que cultura libro exista como subtipo
- que gastronomía receta exista como subtipo
- que consells tenga mapping especial
- que WordPress solo aparezca en adapters

---

## Paso 2. Pedir extracción y clasificación
Usa después:
- `04_prompt_tecnico_extraccion_ocr_clasificacion.txt`

### Qué tiene que devolverte bien
- grouping
- extractores
- OCR
- detectores
- clasificadores
- scoring

### Qué debes revisar
- que no use solo IA
- que la carpeta sea pista, no verdad absoluta
- que el review se active con dudas

---

## Paso 3. Pedir pipeline completo
Cuando la base y la clasificación estén bien, pídele:

- pipeline end-to-end
- watcher
- integración entre módulos
- eventos y estados
- reintentos básicos

### Qué revisar
- que cada etapa use contratos claros
- que guarde bien los estados
- que no mezcle lógica de capas

---

## Paso 4. Pedir panel mínimo
Cuando ya procese lotes de prueba:

- listado de lotes
- detalle de candidatos
- acciones de review
- reprocesado

### Qué revisar
- que sea usable
- que sea mínimo
- que no dedique tiempo a lo visual antes que a lo funcional

---

## Paso 5. Pedir Telegram
Cuando el pipeline ya funcione:

- avisos simples
- solo eventos importantes
- mensajes con contexto útil

---

## Paso 6. Hacer pruebas con lotes reales
Crea una batería real de pruebas con:

1. un DOCX con imágenes bien agrupadas
2. un cartel solo
3. un PDF digital simple
4. un PDF escaneado
5. una agenda con varias actividades
6. una cultura libro
7. una gastronomía receta
8. un consell
9. un lote con conflicto entre carpeta y contenido
10. un lote duplicado

---

## Paso 7. Validar el importador real
Antes de publicar nada de forma automática:

- genera JSON
- prueba en entorno controlado
- verifica que WordPress lo importa bien
- corrige adapters
- solo después valora auto publicación

---

## Paso 8. Activar publicación automática solo en casos seguros
Regla recomendada:

### Auto publish solo si:
- confianza alta
- validación sin errores bloqueantes
- imagen destacada presente
- sin conflictos fuertes
- sin review reasons críticos

### Si no:
- pending review

---

# Checklist técnico final

## Base
- [ ] Docker funcionando
- [ ] volumen Synology montado
- [ ] base de datos funcionando
- [ ] migraciones funcionando
- [ ] .env completo

## Modelo de datos
- [ ] source_batches
- [ ] source_files
- [ ] content_candidates
- [ ] extracted_documents
- [ ] candidate_images
- [ ] canonical_contents
- [ ] validation_reports
- [ ] wordpress_exports
- [ ] processing_events
- [ ] reprocessing_requests

## Extracción
- [ ] DOCX
- [ ] PDF digital
- [ ] PDF OCR
- [ ] imagen OCR
- [ ] limpieza de texto

## Clasificación
- [ ] municipio
- [ ] categoría
- [ ] subtipo
- [ ] scoring
- [ ] review reasons

## Editorial
- [ ] título final
- [ ] resumen final
- [ ] cuerpo HTML
- [ ] structured_fields

## Imágenes
- [ ] optimización
- [ ] destacada
- [ ] inline
- [ ] galería

## WordPress
- [ ] adapters
- [ ] JSON final
- [ ] prueba real de importación

## Operación
- [ ] watcher
- [ ] Telegram
- [ ] panel mínimo
- [ ] reprocesado

---

# Recomendación de uso real

## Orden recomendado
1. Base técnica
2. Extracción y clasificación
3. Pipeline completo
4. Panel
5. Telegram
6. Pruebas reales
7. Importación real
8. Automatización segura
9. Modo revista completa

## Error a evitar
No mezclar desde el principio:
- extracción
- lógica editorial
- nombres reales de WordPress
- reglas de validación
- exportación

Si eso se mezcla pronto, luego mantenerlo será mucho más difícil.

---

# Siguiente mejor acción

Empieza por pedir a Codex la base con el prompt técnico de datos, adapters y pipeline. Cuando eso esté bien, pasa al prompt de extracción y clasificación.
