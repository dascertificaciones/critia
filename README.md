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
- `ADMIN_TOKEN` clave de administrador (alias: `DOCENTE_TOKEN`). Obligatoria, mínimo 6 caracteres; el servidor no arranca sin ella
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

## Seguridad (resumen)

- El alumno recibe un token al entrar (cabecera `X-Alumno`); solo él puede abrir casos, responder, revisar y reflexionar sobre sus intentos.
- Un seudónimo no se puede mover de grupo ni cambiar de equipo; para volver a entrar hay que usar el mismo grupo y equipo.
- Cada intento es una máquina de estados: decisión inicial → revisión → reflexión; nada se reescribe después.
- Repetir un caso ya cerrado sirve para practicar, pero no suma sentidos, racha, insignias ni territorio.
- El caso del detective se valida en el servidor (racha de 3 por mapa).
- Los docentes solo revisan intentos, alertas y resúmenes de sus grupos, y solo asignan sus propios casos a sus propios mapas. Sesión de 12 h; 5 contraseñas falladas bloquean un minuto.
- Todo texto de usuario o del modelo se escapa antes de insertarse en HTML.
