# Critia · La expedición

Tutor gamificado de pensamiento crítico y uso responsable de IA, para estudiantes de 11 a 17 años. Hack4Edu 2026 · Reto 04 "Un tutor que no te da la respuesta".

**Cómo se usa en clase:** antes de dejar una investigación, el docente define el mapa según su tema; los alumnos entrenan la habilidad de pensamiento crítico con respuestas de IA, reciben pistas (nunca la solución) y ganan la insignia; después entregan la tarea real. El docente ve en qué conceptos necesita apoyo cada estudiante.

## Correr en local

    cd backend
    pip install -r requirements.txt
    uvicorn main:app --reload --port 8000

Abrir http://localhost:8000

- Alumno: `/` (mapa), `/caso.html?id=...`, `/insignias.html`, `/tablero.html`
- Docente: `/docente.html` (usuario y contraseña que crea el administrador)
- Administrador: `/docente.html` con usuario vacío y la clave `ADMIN_TOKEN` (o `DOCENTE_TOKEN`); crea profesores
- API: `/docs`

## Variables de entorno

- `SEXTO_DB` ruta de la base SQLite (por defecto `backend/historial.db`)
- `ADMIN_TOKEN` clave de administrador (alias: `DOCENTE_TOKEN`)
- `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL` modelo para generar casos (DeepSeek por defecto)

## Estructura

    backend/asp/                 reglas (diagnostico.dlv, tutor.dlv)
    backend/casos/casos.json     banco base
    backend/casos/docente/       casos inyectados por n8n (provisionales hasta aprobar)
    backend/misiones.json        misiones, postulados, sentidos
    frontend/                    interfaz (HTML/CSS/JS, sin build)
    frontend/assets/insignias/   p01..p12.png

## Reglas del juego (backend/historial.py)

    RACHA_PARA_DETECTIVE = 3
    CASOS_PARA_INSIGNIA = 2

## Respaldo diario (VPS)

    chmod +x /opt/critia/respaldo.sh
    (crontab -l 2>/dev/null; echo "15 3 * * * /opt/critia/respaldo.sh >> /var/log/critia-respaldo.log 2>&1") | crontab -

Guarda `/opt/critia-respaldos/critia-AAAA-MM-DD.tar.gz` (base de datos + casos generados), 30 días.
Restaurar la base: `docker cp historial.db critia:/data/historial.db && docker restart critia`.
