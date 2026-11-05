#!/usr/bin/env bash
# respaldo.sh — Critia
# Copia la base SQLite (del volumen Docker) y los casos generados a /opt/critia-respaldos/AAAA-MM-DD.tar.gz
# Conserva los últimos 30 días. Pensado para cron diario.
set -euo pipefail
DEST=/opt/critia-respaldos
DIA=$(date +%F)
TMP=$(mktemp -d)
mkdir -p "$DEST"

# 1) Base de datos: copia consistente usando el backup de sqlite dentro del contenedor
docker exec critia python3 -c "
import sqlite3; src=sqlite3.connect('/data/historial.db'); dst=sqlite3.connect('/data/historial.respaldo.db'); src.backup(dst); dst.close(); src.close()"
docker cp critia:/data/historial.respaldo.db "$TMP/historial.db"
docker exec critia rm -f /data/historial.respaldo.db

# 2) Casos generados por los docentes (viven en el host, montados en el contenedor)
cp -r /opt/critia/backend/casos/docente "$TMP/casos_docente"

# 3) Empaquetar
tar czf "$DEST/critia-$DIA.tar.gz" -C "$TMP" .
rm -rf "$TMP"

# 4) Conservar 30 días
find "$DEST" -name 'critia-*.tar.gz' -mtime +30 -delete

echo "Respaldo listo: $DEST/critia-$DIA.tar.gz ($(du -h "$DEST/critia-$DIA.tar.gz" | cut -f1))"
