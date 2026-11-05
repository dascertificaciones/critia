"""
main.py — Critia (API con FastAPI)
Arrancar:
    uvicorn main:app --host 0.0.0.0 --port 8000
Variables de entorno:
    SEXTO_DB        ruta de la base SQLite (por defecto backend/historial.db)
    ADMIN_TOKEN     clave de administrador (crea profesores). Acepta DOCENTE_TOKEN como alias.
    LLM_API_KEY, LLM_BASE_URL, LLM_MODEL   para generar casos
    APP_VERSION     versión que se añade a los assets (la pone Docker)

Roles:
    alumno   sin clave; entra con seudónimo, equipo y código de grupo
    docente  usuario/contraseña -> token de sesión (cabecera x-sesion); ve solo sus grupos
    admin    cabecera x-admin con ADMIN_TOKEN; además tiene todo lo del docente sobre todos los grupos
"""
import json
import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import generador
import historial
import motor
import sesion

BASE = Path(__file__).parent
FRONT = BASE.parent / "frontend"
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN") or os.environ.get("DOCENTE_TOKEN", "docente")
META = json.loads((BASE / "misiones.json").read_text(encoding="utf-8"))
VERSION = os.environ.get("APP_VERSION", "dev")

app = FastAPI(title="Critia", version="0.5")


def _err(e):
    raise HTTPException(status_code=400, detail=str(e))


class Quien:
    """Identidad del que llama al panel: admin o docente."""
    def __init__(self, admin=False, docente=None):
        self.admin = admin
        self.docente = docente  # dict {usuario, nombre} o None

    @property
    def usuario(self):
        return "admin" if self.admin else self.docente["usuario"]

    def codigos(self):
        """Grupos que puede ver: None = todos (admin)."""
        if self.admin:
            return None
        return [g["codigo"] for g in historial.grupos_de(self.docente["usuario"])]

    def puede_grupo(self, codigo):
        return self.admin or codigo in (self.codigos() or [])


def _quien(x_admin: str = "", x_sesion: str = "") -> Quien:
    if x_admin and x_admin == ADMIN_TOKEN:
        return Quien(admin=True)
    d = historial.docente_por_token(x_sesion)
    if d:
        return Quien(docente=d)
    raise HTTPException(401, "Inicia sesión como docente")


def _admin(x_admin: str = ""):
    if x_admin != ADMIN_TOKEN:
        raise HTTPException(401, "Clave de administrador incorrecta")


# ---------- Modelos ----------
class AlumnoIn(BaseModel):
    seudonimo: str
    equipo: str
    grupo: str


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


class GenerarIn(BaseModel):
    tema: str
    grado: str = "secundaria (12-15 años)"
    postulado: int
    formato: str = "tres_opciones"
    n: int = 2


class CasoEditIn(BaseModel):
    cambios: dict


class AprobarIn(BaseModel):
    grupos: list[str] = []


class LoginIn(BaseModel):
    usuario: str
    password: str


class DocenteIn(BaseModel):
    usuario: str
    nombre: str
    password: str


class PasswordIn(BaseModel):
    password: str


class GrupoIn(BaseModel):
    nombre: str


# =====================================================================
# Público / alumno
# =====================================================================
@app.get("/api/meta")
def meta():
    return META | {"equipos": historial.EQUIPOS}


def _casos_visibles(seudonimo=None):
    """Banco base + casos generados aprobados para el grupo del alumno."""
    todos, _ = motor.cargar_casos()
    codigo = historial.grupo_de_alumno(seudonimo) if seudonimo else None
    permitidos = historial.casos_del_grupo(codigo) if codigo else set()
    out = {}
    for cid, c in todos.items():
        es_generado = "generado_por" in c or c.get("origen")
        if not es_generado:
            out[cid] = c
        elif not c.get("provisional") and cid in permitidos:
            out[cid] = c
    return out


@app.get("/api/casos")
def casos(seudonimo: Optional[str] = None):
    """Lista de casos sin claves, agrupados por misión, filtrados por el grupo del alumno."""
    vis = _casos_visibles(seudonimo)
    por_mision = {m["n"]: [] for m in META["misiones"]}
    for c in sorted(vis.values(), key=lambda c: (c["mision"], c["id"])):
        por_mision.setdefault(c["mision"], []).append(motor.caso_para_alumno(c))
    return por_mision


@app.get("/api/grupo/{codigo}")
def grupo_publico(codigo: str):
    g = historial.grupo(codigo)
    if not g:
        raise HTTPException(404, "Ese código de grupo no existe")
    return {"codigo": g["codigo"], "nombre": g["nombre"]}


@app.post("/api/alumno")
def alumno(a: AlumnoIn):
    try:
        return historial.registrar_alumno_en_grupo(a.seudonimo.strip(), a.equipo, a.grupo)
    except ValueError as e:
        _err(e)


@app.get("/api/alumno/{seudonimo}/progreso")
def progreso(seudonimo: str):
    if not historial.obtener_alumno(seudonimo):
        raise HTTPException(404, "Alumno no registrado")
    todos, _ = motor.cargar_casos()
    return historial.progreso_alumno(seudonimo, {c["id"]: c["postulado"] for c in todos.values()})


@app.get("/api/insignias/{seudonimo}")
def insignias(seudonimo: str):
    if not historial.obtener_alumno(seudonimo):
        raise HTTPException(404, "Alumno no registrado")
    todos, _ = motor.cargar_casos()
    prog = historial.progreso_alumno(seudonimo, {c["id"]: c["postulado"] for c in todos.values()})
    return [p | {"obtenida": p["n"] in prog["insignias"], "avance": prog["avance_insignias"].get(str(p["n"]), 0),
                 "meta": prog["casos_para_insignia"], "imagen": f"/assets/insignias/p{p['n']:02d}.png"} for p in META["postulados"]]


@app.post("/api/caso/{caso_id}/abrir")
def abrir(caso_id: str, d: AbrirIn):
    if caso_id not in _casos_visibles(d.seudonimo):
        raise HTTPException(404, "Ese caso no está disponible para tu grupo")
    return sesion.abrir(d.seudonimo, caso_id)


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
def tablero(grupo: Optional[str] = None):
    if grupo:
        g = historial.grupo(grupo)
        if not g:
            raise HTTPException(404, "Grupo no existe")
        return {"grupo": {"codigo": g["codigo"], "nombre": g["nombre"]}, "equipos": historial.tablero_equipos_grupo(g["codigo"])}
    return {"grupo": None, "equipos": historial.tablero_equipos()}


# =====================================================================
# Sesión docente
# =====================================================================
@app.post("/api/docente/login")
def docente_login(d: LoginIn):
    s = historial.login_docente(d.usuario, d.password)
    if not s:
        raise HTTPException(401, "Usuario o contraseña incorrectos")
    return s


@app.post("/api/docente/logout")
def docente_logout(x_sesion: str = Header(default="")):
    historial.cerrar_sesion(x_sesion)
    return {"ok": True}


@app.get("/api/docente/yo")
def docente_yo(x_admin: str = Header(default=""), x_sesion: str = Header(default="")):
    q = _quien(x_admin, x_sesion)
    return {"admin": q.admin, "usuario": q.usuario, "nombre": "Administrador" if q.admin else q.docente["nombre"],
            "grupos": historial.grupos_de(q.usuario) if not q.admin else [g for d in historial.listar_docentes() for g in historial.grupos_de(d["usuario"])]}


@app.post("/api/docente/grupos")
def crear_grupo(d: GrupoIn, x_admin: str = Header(default=""), x_sesion: str = Header(default="")):
    q = _quien(x_admin, x_sesion)
    if q.admin:
        raise HTTPException(400, "El administrador no tiene grupos propios; inicia sesión como docente")
    if len(d.nombre.strip()) < 1:
        raise HTTPException(400, "Escribe un nombre")
    return historial.crear_grupo(q.usuario, d.nombre)


@app.put("/api/docente/grupos/{codigo}")
def renombrar_grupo(codigo: str, d: GrupoIn, x_admin: str = Header(default=""), x_sesion: str = Header(default="")):
    q = _quien(x_admin, x_sesion)
    if not q.puede_grupo(codigo):
        raise HTTPException(403, "Ese grupo no es tuyo")
    historial.renombrar_grupo(codigo, d.nombre)
    return {"ok": True}


# =====================================================================
# Panel docente (filtrado por grupos del docente; admin ve todo)
# =====================================================================
def _casos_de(q: Quien):
    todos, _ = motor.cargar_casos()
    out = []
    for c in todos.values():
        es_generado = "generado_por" in c or c.get("origen")
        if not es_generado:
            c = dict(c, base=True); out.append(c); continue
        if q.admin or c.get("docente") == q.usuario:
            c = dict(c, grupos=historial.grupos_del_caso(c["id"])); out.append(c)
    return out


@app.get("/api/docente/casos")
def docente_casos(x_admin: str = Header(default=""), x_sesion: str = Header(default="")):
    return _casos_de(_quien(x_admin, x_sesion))


@app.post("/api/docente/casos/{caso_id}/aprobar")
def docente_aprobar(caso_id: str, d: AprobarIn, x_admin: str = Header(default=""), x_sesion: str = Header(default="")):
    """Quita la marca provisional y asigna el caso a los grupos indicados."""
    q = _quien(x_admin, x_sesion)
    for cod in d.grupos:
        if not q.puede_grupo(cod):
            raise HTTPException(403, f"El grupo {cod} no es tuyo")
    for f in (motor.CASOS_DIR / "docente").glob("*.json"):
        data = json.loads(f.read_text(encoding="utf-8"))
        for c in data.get("casos", []):
            if c["id"] == caso_id:
                if not q.admin and c.get("docente") != q.usuario:
                    raise HTTPException(403, "Ese caso no es tuyo")
                c["provisional"] = False
                c["revisado_por_docente"] = True
                f.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                historial.asignar_caso(caso_id, d.grupos)
                return {"ok": True, "grupos": d.grupos}
    raise HTTPException(404, "Caso no está en la carpeta docente")


@app.put("/api/docente/casos/{caso_id}/grupos")
def docente_asignar(caso_id: str, d: AprobarIn, x_admin: str = Header(default=""), x_sesion: str = Header(default="")):
    q = _quien(x_admin, x_sesion)
    for cod in d.grupos:
        if not q.puede_grupo(cod):
            raise HTTPException(403, f"El grupo {cod} no es tuyo")
    historial.asignar_caso(caso_id, d.grupos)
    return {"ok": True}


@app.get("/api/docente/reflexiones")
def docente_reflexiones(x_admin: str = Header(default=""), x_sesion: str = Header(default="")):
    q = _quien(x_admin, x_sesion)
    todos, _ = motor.cargar_casos()
    out = []
    for r in historial.reflexiones_pendientes_codigos(q.codigos()):
        c = todos.get(r["caso_id"], {})
        r["pregunta"] = c.get("reflexion") or c.get("pregunta")
        r["rubrica"] = c.get("rubrica_reflexion", [])
        out.append(r)
    return out


@app.post("/api/docente/revision")
def docente_revision(d: RevisionIn, x_admin: str = Header(default=""), x_sesion: str = Header(default="")):
    _quien(x_admin, x_sesion)
    historial.guardar_revision(d.intento_id, d.puntaje, d.nota)
    return {"ok": True}


@app.get("/api/docente/sugerencias")
def docente_sugerencias(x_admin: str = Header(default=""), x_sesion: str = Header(default="")):
    q = _quien(x_admin, x_sesion)
    todos, _ = motor.cargar_casos()
    return historial.sugerencias_insignia_codigos({c["id"]: c["postulado"] for c in todos.values()}, q.codigos())


@app.post("/api/docente/insignia")
def docente_insignia(d: InsigniaIn, x_admin: str = Header(default=""), x_sesion: str = Header(default="")):
    q = _quien(x_admin, x_sesion)
    if not q.puede_grupo(historial.grupo_de_alumno(d.seudonimo)):
        raise HTTPException(403, "Ese alumno no está en tus grupos")
    historial.otorgar_insignia(d.seudonimo, d.postulado, q.usuario)
    return {"ok": True}


@app.get("/api/docente/resumen")
def docente_resumen(grupo: Optional[str] = None, x_admin: str = Header(default=""), x_sesion: str = Header(default="")):
    q = _quien(x_admin, x_sesion)
    codigos = q.codigos()
    if grupo:
        if not q.puede_grupo(grupo):
            raise HTTPException(403, "Ese grupo no es tuyo")
        codigos = [grupo]
    todos, _ = motor.cargar_casos()
    r = historial.resumen_grupo_codigos(codigos)
    for c in r["por_caso"]:
        c["titulo"] = todos.get(c["caso_id"], {}).get("titulo", c["caso_id"])
    return r


@app.get("/api/docente/alumnos")
def docente_alumnos(x_admin: str = Header(default=""), x_sesion: str = Header(default="")):
    q = _quien(x_admin, x_sesion)
    return historial.lista_alumnos_codigos(q.codigos())


@app.get("/api/docente/alumnos/{seudonimo}")
def docente_alumno(seudonimo: str, x_admin: str = Header(default=""), x_sesion: str = Header(default="")):
    q = _quien(x_admin, x_sesion)
    if not q.puede_grupo(historial.grupo_de_alumno(seudonimo)):
        raise HTTPException(403, "Ese alumno no está en tus grupos")
    todos, _ = motor.cargar_casos()
    h = historial.historial_alumno(seudonimo)
    for i in h:
        i["titulo"] = todos.get(i["caso_id"], {}).get("titulo", i["caso_id"])
    return h


@app.get("/api/docente/generador/estado")
def generador_estado(x_admin: str = Header(default=""), x_sesion: str = Header(default="")):
    _quien(x_admin, x_sesion)
    return {"configurado": bool(os.environ.get("LLM_API_KEY")), "modelo": generador.MODEL, "base_url": generador.BASE_URL}


@app.post("/api/docente/generar")
def docente_generar(d: GenerarIn, x_admin: str = Header(default=""), x_sesion: str = Header(default="")):
    q = _quien(x_admin, x_sesion)
    if not 1 <= d.n <= 5:
        raise HTTPException(400, "n debe estar entre 1 y 5")
    if d.postulado not in generador.POSTULADOS:
        raise HTTPException(400, "postulado inválido")
    try:
        return generador.generar(d.tema.strip(), d.grado, d.postulado, d.formato, d.n, docente=q.usuario)
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"Error llamando al modelo: {e}")


@app.put("/api/docente/casos/{caso_id}")
def docente_editar_caso(caso_id: str, d: CasoEditIn, x_admin: str = Header(default=""), x_sesion: str = Header(default="")):
    q = _quien(x_admin, x_sesion)
    try:
        return generador.actualizar_caso(caso_id, d.cambios, solo_de=None if q.admin else q.usuario)
    except KeyError:
        raise HTTPException(404, "Solo puedes editar tus propios casos generados")


@app.delete("/api/docente/casos/{caso_id}")
def docente_borrar_caso(caso_id: str, x_admin: str = Header(default=""), x_sesion: str = Header(default="")):
    q = _quien(x_admin, x_sesion)
    if not generador.eliminar_caso(caso_id, solo_de=None if q.admin else q.usuario):
        raise HTTPException(404, "Solo puedes borrar tus propios casos generados")
    historial.asignar_caso(caso_id, [])
    return {"ok": True}


@app.get("/api/docente/alertas")
def docente_alertas(x_admin: str = Header(default=""), x_sesion: str = Header(default="")):
    _quien(x_admin, x_sesion)
    return historial.alerta_casos()


# =====================================================================
# Administrador
# =====================================================================
@app.get("/api/admin/docentes")
def admin_docentes(x_admin: str = Header(default="")):
    _admin(x_admin)
    return historial.listar_docentes()


@app.post("/api/admin/docentes")
def admin_crear_docente(d: DocenteIn, x_admin: str = Header(default="")):
    _admin(x_admin)
    try:
        return historial.crear_docente(d.usuario, d.nombre, d.password)
    except ValueError as e:
        _err(e)


@app.put("/api/admin/docentes/{usuario}/password")
def admin_password(usuario: str, d: PasswordIn, x_admin: str = Header(default="")):
    _admin(x_admin)
    try:
        historial.cambiar_password(usuario, d.password)
    except ValueError as e:
        _err(e)
    return {"ok": True}


@app.put("/api/admin/docentes/{usuario}/activo")
def admin_activo(usuario: str, activo: bool, x_admin: str = Header(default="")):
    _admin(x_admin)
    historial.activar_docente(usuario, activo)
    return {"ok": True}


# =====================================================================
# Frontend
# =====================================================================
if FRONT.exists():
    app.mount("/assets", StaticFiles(directory=FRONT / "assets"), name="assets")

    def _html(f: Path):
        html = f.read_text(encoding="utf-8")
        for a in ["assets/css/estilo.css", "assets/js/iconos.js", "assets/js/api.js"]:
            html = html.replace(a, f"{a}?v={VERSION}")
        return HTMLResponse(html, headers={"Cache-Control": "no-cache, no-store, must-revalidate"})

    @app.get("/")
    def index():
        return _html(FRONT / "index.html")

    @app.get("/{pagina}.html")
    def pagina(pagina: str):
        f = FRONT / f"{pagina}.html"
        if not f.exists():
            raise HTTPException(404)
        return _html(f)
