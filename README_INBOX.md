# WordPress Editorial Automation - Módulo de Origen de Entrada (Inbox)

Este módulo gestiona cómo la aplicación obtiene los nuevos contenidos para procesar, abstrayendo el concepto de "Carpeta Caliente" (Hot Folder) para soportar tanto rutas locales (Docker volumes, Synology montado por red) como servidores remotos (FTP, SFTP).

## Modos Soportados (`InboxMode`)
1. **LOCAL**: Utiliza la ruta especificada en `hot_folder_local_path`. Es el modo recomendado si el Synology está montado directamente en el sistema operativo host.
2. **FTP**: Conecta usando `ftplib` estándar. Ideal para integraciones con servidores antiguos.
3. **SFTP**: Conecta usando `paramiko` a través de SSH. Soporta autenticación por contraseña y por clave privada.
4. **DISABLED**: Detiene por completo la escucha de nuevos contenidos.

## Arquitectura de Clientes (`BaseRemoteInboxClient`)
Todos los clientes implementan una interfaz común para:
- Probar conexión.
- Validar permisos sobre la ruta base.
- Listar contenidos.
- Descargar un lote (`fetch_batch`) a una carpeta de trabajo temporal local.
- Mover o borrar el lote en origen una vez procesado (`move_processed_entry`, `delete_processed_entry`).

El cliente `LocalFolderInboxClient` implementa una protección fuerte contra **Path Traversal**, asegurando que el pipeline no pueda salir de la `base_path` configurada mediante rutas relativas maliciosas (`../../../etc`).

## Descubrimiento de Lotes (`InboxBatchDiscoveryService`)
Este servicio escanea el cliente activo y determina qué constituye un lote procesable:
- Si encuentra una carpeta en la raíz del inbox, la trata como un lote.
- Si encuentra archivos sueltos (ej. `.pdf`), los agrupa en "lotes virtuales" de un solo archivo.
- Filtra y oculta automáticamente extensiones no permitidas y archivos ocultos (`.DS_Store`).

## Integración con el Panel (UI y API)
- El panel de control consume directamente la API `/api/v1/inbox/test-active` para comprobar que la configuración guardada funciona en tiempo real.
- Permite listar el contenido remoto y descubrir lotes manualmente desde la web.

## Polling vs Watchdog (`InboxPollingService`)
Debido a que protocolos como FTP/SFTP no soportan eventos de sistema de archivos en tiempo real de forma eficiente (como inotify), se ha implementado un `InboxPollingService` que consulta el origen cada X segundos.
- En el arranque (`main.py`), si el modo es LOCAL, se usa `watchdog` (inmediato).
- El Polling Service está diseñado para convivir o sustituir al watcher, trayendo los lotes remotos a local y empujándolos al `PipelineOrchestrator` de forma controlada.

## Acciones Finales (Post-Proceso)
En la configuración (`delete_after_import`, `move_after_import`) se decide qué hacer con el lote remoto cuando el pipeline termina. El orquestador llama a `finalize_processed_batch` para limpiar el inbox de entrada y no volver a reprocesarlo en el siguiente escaneo.
