# Critia · La expedición

Tutor gamificado de pensamiento crítico y uso responsable de IA, para secundaria (12-15 años).

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
