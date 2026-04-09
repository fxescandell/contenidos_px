# WordPress Editorial Automation - Fase 4 (Panel Mínimo y Notificaciones)

Esta fase proporciona una interfaz de usuario básica pero muy funcional para revisar y tomar decisiones sobre el contenido procesado, así como un sistema de notificaciones integrado con Telegram.

## Componentes Implementados

### 1. Panel Web Mínimo (`app/templates/` & `app/api/routes/panel.py`)
No se ha construido un SPA (Single Page Application) complejo, sino una interfaz renderizada desde el servidor con Jinja2 y FastAPI. Esto cumple con el requisito de "Panel Mínimo" que sea rápido y libre de mantenimiento pesado.
- **`index.html`**: Un listado de los lotes procesados más recientes. Puedes ver de un vistazo si algún lote se atascó o requiere revisión (`REVIEW_REQUIRED`).
- **`batch_detail.html`**: Muestra qué candidatos a artículo se detectaron dentro de un lote (si entraron varias carpetas juntas).
- **`candidate_detail.html`**: La vista crítica. Aquí puedes comparar lo que el OCR o el extractor sacó del PDF/DOCX (texto bruto limpio) con la **Decisión Editorial Canónica** que el sistema ha propuesto (municipio, categoría, campos estructurados y título).
- **Acciones Rápidas:**
  - `Aprobar Manualmente`: Fuerza la exportación del artículo aunque el sistema tuviera dudas.
  - `Forzar Reprocesado`: Elimina al candidato y vuelve a correr todo el pipeline sobre esos archivos.

### 2. Notificaciones por Telegram (`app/services/notifications/telegram.py`)
Un sistema asíncrono para enviar notificaciones push a tu móvil.
- Implementa `BaseNotifier`.
- Utiliza la API directa de Telegram (`requests.post` a `api.telegram.org`).
- Solo funciona si configuras `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` en el `.env`. Si no están, el sistema ignora las llamadas sin romper la aplicación.
- Usa Emojis (✅, ⚠️, ❌) para dar contexto visual rápido.

### 3. Servicio de Reprocesado (`app/services/reprocessing/service.py`)
Un módulo preparado para no tener que borrar cosas manualmente en la base de datos cuando algo falla.
- La función `reprocess_candidate_sync` está conectada al botón "Forzar Reprocesado" del panel. 
- Elimina en cascada el candidato (y sus validaciones, extracciones, etc.) y llama a `PipelineOrchestrator` para volver a ingerir y procesar la carpeta original.

### 4. App Principal (`main.py`)
Se ha configurado la aplicación FastAPI.
- Se utiliza el concepto de `lifespan` de FastAPI (reemplazando los antiguos `@app.on_event("startup")`).
- **El Watcher se arranca automáticamente en un hilo en background** al levantar FastAPI y se detiene limpiamente al apagar el servidor.

## Cómo probar el panel

1. Configura el archivo `.env`.
2. Asegúrate de tener las dependencias: `pip install -r requirements_api.txt`.
3. Levanta el servidor:
   ```bash
   uvicorn main:app --reload
   ```
4. Abre `http://localhost:8000` en tu navegador.
