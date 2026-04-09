# Despliegue con Docker

Guia rapida para levantar Panxing Contenidos en desarrollo o produccion usando los archivos Docker del proyecto.

## Archivos incluidos

- `Dockerfile`: imagen base de la aplicacion
- `docker-compose.yml`: entorno simple con SQLite en `/data`
- `docker-compose.prod.yml`: entorno de produccion con PostgreSQL
- `.env.example`: variables base para desarrollo / despliegue simple
- `.env.production.example`: variables recomendadas para produccion
- `deploy.sh`: script de ayuda para levantar, parar y ver logs

## Requisitos

- Docker
- Docker Compose (`docker compose`)

## Modo desarrollo o despliegue simple

Usa SQLite persistida en `./data/editorial.db`.

### 1. Preparar variables

```bash
cp .env.example .env
```

Revisa sobre todo:

- `DATABASE_URL`
- `START_WATCHER`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

Valores recomendados al principio:

```env
DATABASE_URL=sqlite:////data/editorial.db
START_WATCHER=True
```

### 2. Levantar el stack

```bash
./deploy.sh dev up
```

### 3. Ver logs

```bash
./deploy.sh dev logs
```

### 4. Parar el stack

```bash
./deploy.sh dev down
```

## Modo produccion

Usa PostgreSQL en contenedor separado y deja el watcher desactivado por defecto.

### 1. Preparar variables

```bash
cp .env.production.example .env.production
```

Edita como minimo:

- `POSTGRES_PASSWORD`
- `DATABASE_URL`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `START_WATCHER`

Ejemplo minimo:

```env
POSTGRES_DB=editorial_db
POSTGRES_USER=editorial
POSTGRES_PASSWORD=cambia_esta_password
DATABASE_URL=postgresql+psycopg2://editorial:cambia_esta_password@postgres:5432/editorial_db
START_WATCHER=False
```

### 2. Levantar produccion

```bash
./deploy.sh prod up
```

### 3. Comprobar estado

```bash
./deploy.sh prod ps
```

### 4. Ver logs

```bash
./deploy.sh prod logs
```

### 5. Reiniciar tras cambios

```bash
./deploy.sh prod restart
```

## URL de acceso

Una vez levantado:

- Aplicacion: `http://localhost:8000`
- Healthcheck usado por Docker: `http://localhost:8000/api/v1/flows/active-mode`

## Persistencia

### Desarrollo

- `./data:/data`
- base de datos SQLite en `/data/editorial.db`
- rutas de trabajo por defecto en `/data/hot_folder`, `/data/working_dir` y `/data/export_dir`

### Produccion

- `./data:/data` para ficheros de trabajo
- volumen `postgres_data` para la base PostgreSQL

## Watcher automatico

El arranque del watcher depende de dos cosas:

1. variable de entorno `START_WATCHER`
2. ajuste guardado en base de datos `enable_watcher`

Solo arranca si ambas estan activadas.

Recomendacion:

- desarrollo: `START_WATCHER=True`
- produccion: `START_WATCHER=False` al principio

## Configuracion funcional desde el panel

Aunque el contenedor se configure con `.env`, la mayor parte de la operativa se guarda en base de datos desde el panel:

- SMB / FTP
- rutas locales
- OCR e IA
- conexiones LLM
- categorias y JSON estricto por categoria
- flujos

Panel de ajustes:

- `http://localhost:8000/settings/general`

## Montajes adicionales para modo local

Si quieres que el contenedor lea carpetas reales del host fuera de `./data`, anade bind mounts en el compose.

Ejemplo:

```yaml
volumes:
  - ./data:/data
  - /ruta/host/hot_folder:/mnt/hot_folder
  - /ruta/host/out_folder:/mnt/out_folder
```

Luego usa esas rutas montadas en la configuracion del panel.

## Comandos utiles

```bash
./deploy.sh dev up
./deploy.sh dev down
./deploy.sh dev logs
./deploy.sh dev ps

./deploy.sh prod up
./deploy.sh prod down
./deploy.sh prod logs
./deploy.sh prod ps
./deploy.sh prod restart
```

## Actualizar la aplicacion

Si cambias codigo o dependencias:

```bash
./deploy.sh prod restart
```

Eso reconstruye la imagen y vuelve a levantar los contenedores.

## Problemas frecuentes

### El contenedor arranca pero no procesa nada

- revisa `START_WATCHER`
- revisa en el panel que `enable_watcher` y `enable_auto_processing` esten activos
- revisa que las rutas SMB/Local esten bien guardadas en ajustes

### El OCR falla

- el contenedor ya incluye `tesseract`, `cat` y `spa`
- si usas OCR por IA, revisa tambien la conexion LLM en el panel

### El export no aparece

- revisa `outfolder` o `outfolder_local_path` en ajustes
- revisa permisos de escritura en las rutas montadas
- revisa logs con `./deploy.sh prod logs`

### La base de datos no conecta en produccion

- verifica que `POSTGRES_PASSWORD` y `DATABASE_URL` coincidan
- espera a que `postgres` pase el healthcheck

## Nota final

El proyecto crea tablas automaticamente al arrancar con `Base.metadata.create_all()`, asi que no hace falta ejecutar migraciones manuales.
