# Roadmap y walkthrough de implementación

## Objetivo
Tener una referencia clara de qué pedirle a Codex, en qué orden, qué revisar en cada fase y cuándo pasar a la siguiente.

---

## Visión general del proyecto

La aplicación final tendrá estas capas:

1. **Base estructural**
   - arquitectura
   - modelos
   - base de datos
   - settings
   - enums
   - estados
   - adapters
   - exportación JSON

2. **Núcleo de procesamiento**
   - watcher
   - ingesta
   - hash y duplicados
   - agrupación por candidato
   - extracción PDF/DOCX/OCR
   - clasificación híbrida
   - scoring

3. **Construcción editorial**
   - normalización canónica
   - contenido HTML final
   - structured fields
   - imagen destacada
   - galería / inline images
   - validación por CPT

4. **Salida y operación**
   - JSON final
   - envío a carpeta de importación
   - revisión
   - reproceso
   - Telegram
   - panel mínimo

5. **Fases avanzadas**
   - publicación directa en WordPress
   - mejora de reglas
   - modo revista completa

---

# Fase 0 — Preparación manual antes de programar

## Qué debes hacer tú

### 0.1 Reunir materiales reales
Prepara una carpeta de referencia con:
- 2 o 3 ejemplos reales de agenda
- 2 ejemplos de cultura general
- 2 ejemplos de libros
- 2 ejemplos de gastronomía general
- 2 ejemplos de receta
- 2 ejemplos de consells
- 2 ejemplos de noticias / entrevistas / deportes / turismo activo / niños
- 1 cartel bueno
- 1 cartel malo
- 1 PDF de revista completa
- varios DOCX con imágenes asociadas

### 0.2 Confirmar carpeta ideal de entrada
Intenta que te entreguen el material con esta estructura:

```text
/entrada
  /cerdanya_320
    /agenda
      /fira-formatge
        cartel.jpg
        texto.docx
        foto1.jpg
        foto2.jpg
```

Esto reduce muchísimo errores.

### 0.3 Confirmar flujo WordPress
Decide que la **V1 saldrá por JSON** hacia tu plugin actual.
No intentes empezar publicando directo.

### 0.4 Preparar carpeta de pruebas
Ten una carpeta de ensayo separada de producción.

---

# Fase 1 — Base estructural del proyecto

## Prompt a usar
- `01_prompt_maestro.md`
- `02_prompt_tecnico_1.md`
- `03_prompt_tecnico_2.md`

## Qué debe construir Codex
- árbol del proyecto
- settings
- Docker
- modelos SQLAlchemy
- Alembic
- enums
- estados
- schemas Pydantic
- canonical model
- adapters base
- export builder
- validadores base

## Qué revisar tú antes de seguir

### Checklist
- [ ] Los enums están claros
- [ ] Los estados no son cadenas sueltas
- [ ] Existe un canonical model neutral
- [ ] WordPress solo aparece en adapters/export
- [ ] Hay tabla para lotes, archivos, candidatos, extracción, canonical contents y exports
- [ ] La featured image está modelada como obligatoria
- [ ] Hay review reasons y validation reports
- [ ] Los adapters especiales existen: agenda, cultura, gastronomía, consells
- [ ] El export builder genera JSON desacoplado

## Cuándo pasar a la siguiente fase
Solo cuando veas que la base está limpia y coherente.

---

# Fase 2 — Extracción, OCR y clasificación híbrida

## Prompt a usar
- `04_prompt_tecnico_3_extraccion_clasificacion.md`

## Qué debe construir Codex
- grouping service
- extractores PDF/DOCX/imagen
- OCR
- cleaners
- detectores de señales
- clasificadores por reglas
- subtype detectors
- contradiction detector
- scoring engine
- decision engine

## Qué revisar tú

### Checklist funcional
- [ ] Un PDF digital no dispara OCR innecesario
- [ ] Un PDF escaneado sí activa OCR
- [ ] Un cartel genera texto usable
- [ ] Una carpeta por artículo genera un candidato fuerte
- [ ] Una carpeta genérica con imágenes mezcladas baja la confianza
- [ ] Agenda detecta fechas
- [ ] Cultura libro detecta libro
- [ ] Gastronomía receta detecta receta
- [ ] Si carpeta y contenido se contradicen, se marca revisión
- [ ] Hay señales y explicaciones, no solo un score

## Prueba recomendada
Haz una carpeta de test con 10 casos distintos y mira qué clasifica bien y qué manda a revisión.

---

# Fase 3 — Builder editorial y normalización final

## Qué debes pedirle a Codex después
Pídele algo así:

> Ahora implementa la capa editorial y el CanonicalContent builder usando los contratos existentes. Quiero que reciba grouping, extracción, clasificación e imágenes procesadas y construya el contenido final neutral, con título, resumen, HTML, structured_fields, featured_image y warnings, sin conocer WordPress.

## Qué debe construir
- editorial builder
- title resolver
- summary resolver
- HTML composer
- imagen destacada
- inserción inline simple
- galería cuando aplique
- structured_fields por categoría

## Qué revisar tú
- [ ] No inventa datos
- [ ] Si el texto ya está bien, lo respeta
- [ ] Si el texto es corto, lo amplía con prudencia
- [ ] Si solo hay cartel, crea una pieza breve útil
- [ ] Las imágenes tienen sentido dentro del artículo
- [ ] Los structured_fields salen limpios y canónicos

---

# Fase 4 — Adapters WordPress y JSON final

## Qué debes pedirle a Codex

> Ahora implementa los adapters definitivos de WordPress y el export builder para generar JSON compatible con mi importador actual. Usa el CanonicalContentItem y no mezcles WordPress en capas anteriores.

## Qué debe construir
- AgendaWordPressAdapter
- CulturaWordPressAdapter
- GastronomiaWordPressAdapter
- ConsellsWordPressAdapter
- resto de adapters
- exportación JSON por artículo
- exportación por lote opcional
- validación final antes de export

## Qué revisar tú
- [ ] Los nombres de campos reales de WordPress solo aparecen aquí
- [ ] Agenda mapea fechas correctamente
- [ ] Cultura libro rellena campos de libro
- [ ] Gastronomía receta marca el subtipo correcto
- [ ] Consells usa su mapping especial
- [ ] El JSON se parece a tus exports reales
- [ ] El JSON lo acepta tu plugin sin romperse

## Prueba crítica
Haz una importación real en un entorno de staging.

---

# Fase 5 — Watcher, ingesta y operación completa

## Qué debes pedirle a Codex

> Ahora conecta todo el pipeline end-to-end: watcher del Synology, ingesta, registro de lotes, hash de archivos, ejecución por fases, persistencia de resultados, exportación y estado final.

## Qué debe construir
- watcher
- scanner de archivos
- cálculo de hash
- registro de lotes
- ejecución de pipeline por batch
- control de errores
- control de estados
- no reprocesado si no cambió
- reproceso si cambió

## Qué revisar tú
- [ ] No procesa dos veces lo mismo
- [ ] Si cambia el lote, lo detecta
- [ ] Si falla una fase, queda registrada
- [ ] Puedes relanzar el batch
- [ ] Los logs sirven para entender el fallo

---

# Fase 6 — Telegram y panel mínimo

## Qué debes pedirle a Codex

> Ahora añade notificaciones Telegram y un panel web mínimo con FastAPI + Jinja2 para ver lotes, candidatos, revisión, JSON generado y reprocesado.

## Qué debe construir
- Telegram notifier
- vistas de lotes
- detalle de candidato
- texto extraído
- clasificación propuesta
- estado
- botón de reproceso
- JSON generado

## Qué revisar tú
- [ ] Los avisos de Telegram son útiles
- [ ] Los errores llegan claros
- [ ] Puedes ver rápidamente qué está pendiente
- [ ] Puedes localizar por qué algo fue a revisión

---

# Fase 7 — Endurecimiento y pruebas reales

## Qué debes hacer
Probar con lotes reales y medir:
- precisión de clasificación
- precisión de agenda
- calidad del OCR
- calidad de featured image
- aceptación del JSON por el plugin
- casos que van a revisión

## Qué pedirle a Codex
- mejora de rulesets
- mejora de asociación de imágenes
- mejora de extractores
- más tests
- ajustes de thresholds

## Qué revisar tú
- [ ] El sistema no es demasiado agresivo publicando
- [ ] Tampoco manda todo a revisión
- [ ] Los thresholds están equilibrados
- [ ] Las agendas no salen rotas

---

# Fase 8 — Publicación directa a WordPress

## Solo cuando la V1 esté estable

## Qué pedirle a Codex

> Añade una segunda vía de salida además del JSON: publicación directa a WordPress vía API o integración segura, manteniendo el export JSON como fallback.

## Qué revisar tú
- [ ] Sigue existiendo salida por JSON
- [ ] La publicación directa no rompe la trazabilidad
- [ ] Puedes dejar contenido en draft / pending / publish

---

# Fase 9 — Modo revista completa

## Qué debes pedirle a Codex

> Implementa el modo revista completa: a partir de un PDF digital de una revista entera, segmenta artículos, detecta límites, clasifica cada pieza y genera salidas independientes.

## Qué revisar tú
- [ ] Detecta cortes razonables entre artículos
- [ ] No mezcla artículos cercanos
- [ ] Clasifica bien por sección
- [ ] Si no está claro, manda a revisión

## Importante
Esto debe ser V2 o V3. No lo metas al principio.

---

# Orden recomendado real de trabajo con Codex

1. Prompt maestro
2. Prompt técnico 1
3. Prompt técnico 2
4. Prompt técnico 3
5. Builder editorial
6. Adapters WordPress
7. Watcher e ingesta
8. Telegram y panel
9. Optimización
10. Publicación directa
11. Revista completa

---

# Walkthrough operativo recomendado

## Paso 1
Dale a Codex el prompt maestro.

## Paso 2
Dale el prompt técnico 1.
Pídele que no avance a la fase siguiente sin cerrar bien arquitectura, modelos, config y Docker.

## Paso 3
Dale el prompt técnico 2.
Pídele código real de la base estructural.

## Paso 4
Dale el prompt técnico 3.
Pídele grouping, extractores, reglas, clasificación y scoring.

## Paso 5
Pídele el builder editorial neutral.

## Paso 6
Pídele los adapters WordPress y el export JSON final.

## Paso 7
Pídele el watcher y el pipeline completo.

## Paso 8
Pídele panel y Telegram.

## Paso 9
Prueba con lotes reales.

## Paso 10
Solo si todo va bien, añade publicación directa y revista completa.

---

# Criterios de aceptación del MVP

Tu MVP está listo cuando cumple esto:

- [ ] Detecta nuevos lotes
- [ ] Calcula hashes
- [ ] Agrupa candidatos razonablemente bien
- [ ] Extrae texto de PDF, DOCX e imagen
- [ ] Clasifica municipio, categoría y subtipo
- [ ] Detecta dudas y las manda a revisión
- [ ] Procesa imágenes
- [ ] Genera JSON válido
- [ ] Tu plugin lo importa correctamente
- [ ] Puedes reprocesar
- [ ] Recibes aviso por Telegram
- [ ] Puedes revisar casos dudosos en un panel mínimo

---

# Recomendación final

No intentes tener la versión perfecta desde el día 1.
La mejor estrategia es:

1. base sólida
2. pipeline estable
3. JSON funcionando
4. revisión manual segura
5. mejora de precisión
6. solo después publicación directa y revista completa
