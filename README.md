# Sexto Sentido · La expedición

Tutor gamificado de pensamiento crítico y uso responsable de IA, para secundaria (12-15 años).

## Correr en local

    cd backend
    pip install -r requirements.txt
    uvicorn main:app --reload --port 8000

Abrir http://localhost:8000

- Alumno: `/` (mapa), `/caso.html?id=...`, `/insignias.html`, `/tablero.html`
- Docente: `/docente.html` (clave por defecto `docente`; cambiar con la variable `DOCENTE_TOKEN`)
- API: `/docs`

## Variables de entorno

- `SEXTO_DB` ruta de la base SQLite (por defecto `backend/historial.db`)
- `DOCENTE_TOKEN` clave del panel docente

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
