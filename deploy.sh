#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-dev}"
ACTION="${2:-up}"

if [[ "$MODE" == "prod" ]]; then
  COMPOSE_FILE="docker-compose.prod.yml"
  ENV_FILE=".env.production"
  EXAMPLE_FILE=".env.production.example"
else
  COMPOSE_FILE="docker-compose.yml"
  ENV_FILE=".env"
  EXAMPLE_FILE=".env.example"
fi

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Falta $ENV_FILE"
  echo "Crea el archivo a partir de $EXAMPLE_FILE antes de desplegar."
  exit 1
fi

case "$ACTION" in
  up)
    docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d --build
    ;;
  down)
    docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" down
    ;;
  restart)
    docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" down
    docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d --build
    ;;
  logs)
    docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" logs -f
    ;;
  ps)
    docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" ps
    ;;
  pull)
    docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" pull
    ;;
  *)
    echo "Uso: ./deploy.sh [dev|prod] [up|down|restart|logs|ps|pull]"
    exit 1
    ;;
esac
