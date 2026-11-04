"""
main.py — Sexto Sentido (API con FastAPI)
Arrancar:
    uvicorn main:app --host 0.0.0.0 --port 8000
Variables de entorno opcionales:
    SEXTO_DB        ruta de la base SQLite (por defecto backend/historial.db)
    DOCENTE_TOKEN   clave para el panel del docente (por defecto "docente")
"""
import json
import os
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import historial
import motor
import sesion

BASE = Path(__file__).parent
FRONT = BASE.parent / "frontend"
DOCENTE_TOKEN = os.environ.get("DOCENTE_TOKEN", "docente")
META = json.loads((BASE / "misiones.json").read_text(encoding="utf-8"))

app = FastAPI(title="Sexto Sentido", version="0.4")


def _err(e):
    raise HTTPException(status_code=400, detail=str(e))


def _docente(token):
    if token != DOCENTE_TOKEN:
        raise HTTPException(status_code=401, detail="Clave de docente incorrecta")


# ---------- Modelos ----------
class AlumnoIn(BaseModel):
    seudonimo: str
    equipo: str


class AbrirIn(BaseModel):
    seudonimo: str


class ResponderIn(BaseModel):
    clave: str
    confianza: int
    justificacion: str = ""


class RevisarIn(BaseModel):
    clave: str
    confianza: int


class TextoIn(BaseModel):
    texto: str


class RevisionIn(BaseModel):
    intento_id: int
    puntaje: int
    nota: str = ""


class InsigniaIn(BaseModel):
    seudonimo: str
    postulado: int


# ---------- Público / alumno ----------
@app.get("/api/meta")
def meta():
    return META | {"equipos": historial.EQUIPOS}


@app.get("/api/casos")
def casos():
    """Lista de casos sin claves, agrupados por misión."""
    todos, _ = motor.cargar_casos()
    por_mision = {m["n"]: [] for m in META["misiones"]}
    for c in sorted(todos.values(), key=lambda c: (c["mision"], c["id"])):
        por_mision.setdefault(c["mision"], []).append(motor.caso_para_alumno(c))
    return por_mision


@app.get("/api/insignias/{seudonimo}")
def insignias(seudonimo: str):
    """Vitrina: los 12 postulados con estado para este alumno."""
    if not historial.obtener_alumno(seudonimo):
        raise HTTPException(404, "Alumno no registrado")
    todos, _ = motor.cargar_casos()
    prog = historial.progreso_alumno(seudonimo, {c["id"]: c["postulado"] for c in todos.values()})
    out = []
    for p in META["postulados"]:
        n = p["n"]
        out.append(p | {
            "obtenida": n in prog["insignias"],
            "avance": prog["avance_insignias"].get(str(n), 0),
            "meta": prog["casos_para_insignia"],
            "imagen": f"/assets/insignias/p{n:02d}.png",
        })
    return out


@app.post("/api/alumno")
def alumno(a: AlumnoIn):
    try:
        return historial.registrar_alumno(a.seudonimo.strip(), a.equipo)
    except ValueError as e:
        _err(e)


@app.get("/api/alumno/{seudonimo}/progreso")
def progreso(seudonimo: str):
    if not historial.obtener_alumno(seudonimo):
        raise HTTPException(404, "Alumno no registrado")
    todos, _ = motor.cargar_casos()
    return historial.progreso_alumno(seudonimo, {c["id"]: c["postulado"] for c in todos.values()})


@app.post("/api/caso/{caso_id}/abrir")
def abrir(caso_id: str, d: AbrirIn):
    try:
        return sesion.abrir(d.seudonimo, caso_id)
    except KeyError:
        raise HTTPException(404, "Caso no existe")


@app.post("/api/intento/{intento_id}/responder")
def responder(intento_id: int, d: ResponderIn):
    try:
        r = sesion.responder(intento_id, d.clave, d.confianza, d.justificacion)
    except (ValueError, KeyError, TypeError) as e:
        _err(e)
    r.pop("hechos", None)
    return r


@app.post("/api/intento/{intento_id}/revisar")
def revisar(intento_id: int, d: RevisarIn):
    try:
        r = sesion.revisar(intento_id, d.clave, d.confianza)
    except (ValueError, KeyError, TypeError) as e:
        _err(e)
    r.pop("hechos", None)
    return r


@app.post("/api/intento/{intento_id}/reflexion")
def reflexion(intento_id: int, d: TextoIn):
    return sesion.reflexionar(intento_id, d.texto)


@app.post("/api/intento/{intento_id}/duda")
def duda(intento_id: int):
    return sesion.reportar_duda(intento_id)


@app.get("/api/tablero")
def tablero():
    return historial.tablero_equipos()


# ---------- Docente ----------
@app.get("/api/docente/casos")
def docente_casos(x_docente: str = Header(default="")):
    _docente(x_docente)
    todos, _ = motor.cargar_casos()
    return list(todos.values())


@app.post("/api/docente/casos/{caso_id}/aprobar")
def docente_aprobar(caso_id: str, x_docente: str = Header(default="")):
    """Quita la marca provisional a un caso de la carpeta docente/."""
    _docente(x_docente)
    for f in (motor.CASOS_DIR / "docente").glob("*.json"):
        data = json.loads(f.read_text(encoding="utf-8"))
        cambiado = False
        for c in data.get("casos", []):
            if c["id"] == caso_id:
                c["provisional"] = False
                c["revisado_por_docente"] = True
                cambiado = True
        if cambiado:
            f.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            return {"ok": True, "archivo": f.name}
    raise HTTPException(404, "Caso no está en la carpeta docente")


@app.get("/api/docente/reflexiones")
def docente_reflexiones(x_docente: str = Header(default="")):
    _docente(x_docente)
    todos, _ = motor.cargar_casos()
    out = []
    for r in historial.reflexiones_pendientes():
        c = todos.get(r["caso_id"], {})
        r["pregunta"] = c.get("reflexion") or c.get("pregunta")
        r["rubrica"] = c.get("rubrica_reflexion", [])
        out.append(r)
    return out


@app.post("/api/docente/revision")
def docente_revision(d: RevisionIn, x_docente: str = Header(default="")):
    _docente(x_docente)
    historial.guardar_revision(d.intento_id, d.puntaje, d.nota)
    return {"ok": True}


@app.get("/api/docente/sugerencias")
def docente_sugerencias(x_docente: str = Header(default="")):
    _docente(x_docente)
    todos, _ = motor.cargar_casos()
    return historial.sugerencias_insignia({c["id"]: c["postulado"] for c in todos.values()})


@app.post("/api/docente/insignia")
def docente_insignia(d: InsigniaIn, x_docente: str = Header(default="")):
    _docente(x_docente)
    historial.otorgar_insignia(d.seudonimo, d.postulado)
    return {"ok": True}


@app.get("/api/docente/resumen")
def docente_resumen(x_docente: str = Header(default="")):
    _docente(x_docente)
    todos, _ = motor.cargar_casos()
    r = historial.resumen_grupo()
    for c in r["por_caso"]:
        c["titulo"] = todos.get(c["caso_id"], {}).get("titulo", c["caso_id"])
    return r


@app.get("/api/docente/alumnos")
def docente_alumnos(x_docente: str = Header(default="")):
    _docente(x_docente)
    return historial.lista_alumnos()


@app.get("/api/docente/alumnos/{seudonimo}")
def docente_alumno(seudonimo: str, x_docente: str = Header(default="")):
    _docente(x_docente)
    todos, _ = motor.cargar_casos()
    h = historial.historial_alumno(seudonimo)
    for i in h:
        i["titulo"] = todos.get(i["caso_id"], {}).get("titulo", i["caso_id"])
    return h


@app.get("/api/docente/alertas")
def docente_alertas(x_docente: str = Header(default="")):
    _docente(x_docente)
    return historial.alerta_casos()


# ---------- Frontend ----------
if FRONT.exists():
    app.mount("/assets", StaticFiles(directory=FRONT / "assets"), name="assets")

    @app.get("/")
    def index():
        f = FRONT / "index.html"
        if not f.exists():
            return {"mensaje": "API de Sexto Sentido activa. La interfaz aún no está construida. Documentación en /docs"}
        return FileResponse(f)

    @app.get("/{pagina}.html")
    def pagina(pagina: str):
        f = FRONT / f"{pagina}.html"
        if not f.exists():
            raise HTTPException(404)
        return FileResponse(f)
