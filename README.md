# Critia · La expedición

Tutor gamificado de pensamiento crítico y uso responsable de IA, para estudiantes de 11 a 17 años. Hack4Edu 2026 · Reto 04 "Un tutor que no te da la respuesta".

**Cómo se usa en clase:** antes de dejar una investigación, el docente define el mapa según su tema; los alumnos entrenan la habilidad de pensamiento crítico con respuestas de IA, reciben pistas (nunca la solución) y ganan la insignia; después entregan la tarea real. El docente ve en qué conceptos necesita apoyo cada estudiante.

## Alcance

Critia es un prototipo presentado en Hack4Edu 2026. No ha pasado por un piloto con estudiantes ni cuenta con evidencia de eficacia educativa. Registra el proceso de cada decisión (respuesta inicial, confianza, pista, revisión, reflexión) para que el docente lo consulte; que un alumno corrija tras la pista muestra revisión en ese caso, no transferencia a casos nuevos. El tutor no interpreta el razonamiento escrito, no verifica fuentes en internet, no detecta contenido manipulado y no sustituye al docente. Funciona con un servidor accesible por red (no es una aplicación sin conexión); la generación de casos requiere un proveedor externo.

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

## Procedencia del trabajo

Las bases de Hack4Edu 2026 piden identificar qué existía antes del hackatón y qué se desarrolló durante él.

**Antes del hackatón: Sexto Sentido (documento de diseño, octubre–noviembre de 2026).** Un informe técnico-pedagógico, orientado entonces al Reto 07, que describía un prototipo *objetivo* (no ejecutado ni validado, como el propio documento aclara): un tutor de consola en Python con motor de decisión en Answer Set Programming (DLV), un banco previsto de 23 problemas de razonamiento, 4 actividades escolares y 8 escenarios de alfabetización en IA (AI-LIM-001 a 008), el ciclo decisión → confianza → intervención → revisión → explicación, la separación entre clave editorial y política pedagógica, y los límites de seguridad (no diagnosticar psicológicamente, no calificar prosa automáticamente). De ahí Critia conserva **las ideas**: el ciclo de interacción, la tutoría explicable por reglas ASP con acción y motivo, los 12 postulados de pensamiento crítico y la familia de errores. No se reutilizó código de Sexto Sentido: no existía una implementación funcional.

**Durante el hackatón (Critia, 4–5 de noviembre de 2026), desarrollado desde cero:**
- Backend FastAPI + SQLite, motor clingo con `diagnostico.dlv` y `tutor.dlv`, máquina de estados de intentos, sesiones de alumno y docente, controles de acceso.
- Frontend web (mapa de expedición, caso, insignias, tablero, Universo, panel docente, guía) con diseño propio.
- Banco de 31 casos escritos para este proyecto, centrados en respuestas de IA, en tres niveles por edad y con habilidad/autor explícitos (Paul y Elder, Facione, Ennis, Lipman).
- Generador supervisado de casos con DeepSeek (filtros automáticos + aprobación docente), grupos compartidos, mapas por profesor, insignias por habilidad, territorios y Universo, bono de racha e isla del detective.
- Despliegue en Hostinger (Docker + Traefik) en https://hackaton.proyecto.digital, respaldos diarios.
- Reorientación al **Reto 04 "Un tutor que no te da la respuesta"** y la secuencia didáctica "entrenar antes de investigar".

## Créditos y atribución

- Autor y dirección del proyecto: Erandi Carrasco Alcántara (Universidad Digital del Estado de México, Hack4Edu 2026).
- Código y contenidos redactados con asistencia de IA (Claude, Anthropic) bajo dirección y revisión del autor.
- Ilustraciones del Universo (continente y mar) e insignias: generadas con Higgsfield a partir de indicaciones del autor. Escudos de equipo: aportados por el autor.
- Logotipo de UDEMEX: propiedad de la Universidad Digital del Estado de México; se usa con fines institucionales del proyecto.
- Modelo de lenguaje para generación de casos: DeepSeek (API). Motor lógico: clingo (Potassco).
- Licencia del código: MIT (ver `LICENSE`). Los casos, la guía y los textos pedagógicos se comparten bajo la misma licencia.
