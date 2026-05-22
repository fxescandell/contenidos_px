# WordPress Editorial Automation - Fase 5 (Configuración Dinámica)

Esta fase implementa un panel de configuración completo y persistente desde el cual gobernar el comportamiento del pipeline sin tener que tocar variables de entorno ni reiniciar el servidor constantemente.

## Componentes Principales

### 1. Base de Datos y Modelos (`db/settings_models.py`)
- **`SystemSetting`**: Tabla principal que almacena cada clave de configuración (`project_name`, `telegram_bot_token`, etc.). Soporta tipado básico (Boolean, Integer, String) y una bandera `is_secret` vital para la seguridad.
- **`SettingsAuditLog`**: Tabla de auditoría que registra **quién** cambió **qué** valor y **cuándo**, enmascarando los secretos (contraseñas/tokens) para evitar filtraciones en base de datos.

### 2. Resolutor de Configuración (`services/settings/service.py`)
El `SettingsResolver` es el puente híbrido entre la Base de Datos y las variables de entorno.
- Posee una caché en memoria para no saturar la base de datos consultando la clave de Telegram en cada paso del pipeline.
- Se ha diseñado para que devuelva primero lo que hay en BD. Si la BD está vacía o la clave no existe, hace un "fallback" automático al `.env`.
- Cuando el usuario guarda en el panel web, el sistema recarga la caché automáticamente.

### 3. Clientes Remotos (`services/remote/clients.py`)
Aunque el pipeline en este proyecto lee de un disco montado, he dejado construida la abstracción completa para:
- `LocalFolderInboxClient`: Verifica permisos de lectura y escritura en la ruta caliente local.
- `FtpRemoteInboxClient`: Abstracción (con `ftplib`) para leer de un servidor FTP tradicional.
- `SftpRemoteInboxClient`: Abstracción (con `paramiko`) para leer de un servidor SSH seguro.

Todas las clases implementan un método `test_connection()` que se dispara directamente desde el Panel de Control Web.

### 4. Endpoints y Vistas (`api/routes/settings.py` & `templates/settings/`)
Se ha añadido la ruta `/settings` con un diseño clásico de barra lateral (Sidebar) y contenido a la derecha.
- **Seguridad UI:** Si un campo está marcado como `is_secret` (como el token de Telegram), el servidor no lo manda a la vista HTML, sino que envía la máscara `********`. Si el usuario envía el formulario de nuevo con la máscara, el servidor sabe que **no debe sobrescribir** la contraseña real en base de datos.
- **Botones de Prueba (Test Tools):** Hay botones incrustados en cada categoría ("Probar Telegram", "Probar FTP", "Probar SFTP") que llaman a endpoints `/test/telegram`, etc., de forma asíncrona mediante un pequeño script JavaScript (Fetch API) y pintan el resultado de la conexión sin recargar la página.

## Cómo Usarlo
1. En el panel principal de Lotes (`http://localhost:8000/`), ahora verás un botón **"⚙️ Configuración"** arriba a la derecha.
2. Entra y navega por las categorías (General, Telegram, Inbox...).
3. Si cambias el Token de Telegram y le das a "Probar Telegram", te enviará un mensaje real si está bien configurado.
4. El botón "Recargar caché" te permite forzar la actualización de memoria si has modificado la base de datos a mano por detrás.

## Pruebas
Se han añadido test E2E en `tests/test_phase5.py` para asegurar que el panel carga, guarda datos y, sobre todo, **oculta los tokens secretos** al devolver el HTML.
Para correrlos:
```bash
source venv/bin/activate
python -m pytest tests/
```