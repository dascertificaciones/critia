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
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN") or os.environ.get("DOCENTE_TOKEN") or ""
if not ADMIN_TOKEN or ADMIN_TOKEN == "docente" or len(ADMIN_TOKEN) < 6:
    raise RuntimeError("Configura ADMIN_TOKEN (mínimo 6 caracteres, distinto de 'docente') antes de arrancar Critia")
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
        return self.admin or historial.es_miembro(self.usuario, codigo)

    def puede_mapa(self, mapa_id, solo_propio=False):
        """Puede ver el mapa si es miembro del grupo; con solo_propio, además debe ser su autor."""
        m = historial.mapa(mapa_id)
        if not m:
            return False
        if self.admin:
            return True
        if not historial.es_miembro(self.usuario, m["codigo"]):
            return False
        return (m["docente"] == self.usuario) if solo_propio else True


def _quien(x_admin: str = "", x_sesion: str = "") -> Quien:
    if x_admin and x_admin == ADMIN_TOKEN:
        return Quien(admin=True)
    d = historial.docente_por_token(x_sesion)
    if d:
        return Quien(docente=d)
    raise HTTPException(401, "Inicia sesión como docente")


def _alumno(x_alumno: str = "", seudonimo: Optional[str] = None) -> str:
    """Seudónimo dueño del token de alumno (cabecera x-alumno). Si se indica seudónimo, debe coincidir."""
    quien = historial.alumno_por_token(x_alumno)
    if not quien:
        raise HTTPException(401, "Vuelve a entrar con tu código de grupo y tu seudónimo")
    if seudonimo and seudonimo != quien:
        raise HTTPException(403, "Ese progreso no es tuyo")
    return quien


def _intento_de(intento_id: int, x_alumno: str):
    quien = _alumno(x_alumno)
    it = historial.obtener_intento(intento_id)
    if not it or it["seudonimo"] != quien:
        raise HTTPException(403, "Ese intento no es tuyo")
    return it


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
    mapa: Optional[int] = None


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
    mapa: Optional[int] = None


class GenerarIn(BaseModel):
    tema: str
    nivel: int = 2
    postulado: Optional[int] = None
    postulados: Optional[list[int]] = None
    formato: str = "tres_opciones"
    n: int = 2


class CasoEditIn(BaseModel):
    cambios: dict


class AprobarIn(BaseModel):
    mapas: list[int] = []


class UnirseIn(BaseModel):
    codigo: str


class MapaIn(BaseModel):
    codigo: Optional[str] = None
    nombre: str


class LoginIn(BaseModel):
    usuario: str
    password: str


class DocenteIn(BaseModel):
    usuario: str
    nombre: str
    password: str


class PasswordIn(BaseModel):
    password: str


class TransferenciaIn(BaseModel):
    mapa: int
    aplico: bool
    nota: str = ""


class GrupoIn(BaseModel):
    nombre: str
    nivel: Optional[int] = None


# =====================================================================
# Público / alumno
# =====================================================================
@app.get("/api/meta")
def meta():
    return META | {"equipos": historial.EQUIPOS}


def _mapa_de(seudonimo, mapa_id):
    """Valida que el mapa pertenezca al grupo del alumno; si no hay mapa, usa el primero del grupo."""
    codigo = historial.grupo_de_alumno(seudonimo)
    if not codigo:
        return None
    if mapa_id:
        m = historial.mapa(mapa_id)
        if m and m["codigo"] == codigo:
            return m["id"]
    ms = historial.mapas_de_grupo(codigo)
    return ms[0]["id"] if ms else None


def _casos_visibles(seudonimo=None, mapa_id=None):
    """Banco base del nivel del grupo + casos generados aprobados para el mapa elegido.
    Sin seudónimo (vista previa) se muestra todo el banco base."""
    todos, _ = motor.cargar_casos()
    nivel = historial.nivel_de_alumno(seudonimo) if seudonimo else None
    mid = _mapa_de(seudonimo, mapa_id) if seudonimo else None
    permitidos = historial.casos_del_mapa(mid) if mid else set()
    out = {}
    for cid, c in todos.items():
        es_generado = "generado_por" in c or c.get("origen")
        if not es_generado:
            if nivel is None or c.get("nivel", 2) == nivel or c.get("especial"):
                out[cid] = c
        elif not c.get("provisional") and cid in permitidos:
            out[cid] = c
    return out


@app.get("/api/casos")
def casos(seudonimo: Optional[str] = None, mapa: Optional[int] = None):
    """Lista de casos sin claves, agrupados por misión, filtrados por nivel del grupo y mapa elegido."""
    vis = _casos_visibles(seudonimo, mapa)
    por_mision = {m["n"]: [] for m in META["misiones"]}
    for c in sorted(vis.values(), key=lambda c: (c["mision"], c["id"])):
        por_mision.setdefault(c["mision"], []).append(motor.caso_para_alumno(c))
    return por_mision


@app.get("/api/grupo/{codigo}")
def grupo_publico(codigo: str):
    g = historial.grupo(codigo)
    if not g:
        raise HTTPException(404, "Ese código de grupo no existe")
    return {"codigo": g["codigo"], "nombre": g["nombre"], "nivel": g.get("nivel") or 2,
            "mapas": [{"id": m["id"], "nombre": m["nombre"], "docente": m["docente_nombre"] or m["docente"]} for m in historial.mapas_de_grupo(g["codigo"])]}


@app.post("/api/alumno")
def alumno(a: AlumnoIn):
    try:
        return historial.registrar_alumno_en_grupo(a.seudonimo.strip(), a.equipo, a.grupo)
    except ValueError as e:
        _err(e)


@app.get("/api/alumno/{seudonimo}/progreso")
def progreso(seudonimo: str, mapa: Optional[int] = None, x_alumno: str = Header(default="")):
    _alumno(x_alumno, seudonimo)
    if not historial.obtener_alumno(seudonimo):
        raise HTTPException(404, "Alumno no registrado")
    todos, _ = motor.cargar_casos()
    return historial.progreso_alumno(seudonimo, {c["id"]: c["postulado"] for c in todos.values()}, _mapa_de(seudonimo, mapa))


@app.get("/api/insignias/{seudonimo}")
def insignias(seudonimo: str, mapa: Optional[int] = None, x_alumno: str = Header(default="")):
    _alumno(x_alumno, seudonimo)
    if not historial.obtener_alumno(seudonimo):
        raise HTTPException(404, "Alumno no registrado")
    todos, _ = motor.cargar_casos()
    prog = historial.progreso_alumno(seudonimo, {c["id"]: c["postulado"] for c in todos.values()}, _mapa_de(seudonimo, mapa))
    return [p | {"obtenida": p["n"] in prog["insignias"], "avance": prog["avance_insignias"].get(str(p["n"]), 0),
                 "meta": prog["casos_para_insignia"], "imagen": f"/assets/insignias/p{p['n']:02d}.png",
                 "habilidad_nombre": (motor.habilidad_de({"postulado": p["n"]}) or {}).get("nombre"),
                 "habilidad_autor": (motor.habilidad_de({"postulado": p["n"]}) or {}).get("autor")} for p in META["postulados"]]


@app.post("/api/caso/{caso_id}/abrir")
def abrir(caso_id: str, d: AbrirIn, x_alumno: str = Header(default="")):
    _alumno(x_alumno, d.seudonimo)
    vis = _casos_visibles(d.seudonimo, d.mapa)
    if caso_id not in vis:
        raise HTTPException(404, "Ese caso no está disponible para tu grupo")
    mid = _mapa_de(d.seudonimo, d.mapa)
    if vis[caso_id].get("especial") == "detective":
        todos, _ = motor.cargar_casos()
        prog = historial.progreso_alumno(d.seudonimo, {c["id"]: c["postulado"] for c in todos.values()}, mid)
        if not prog["detective_desbloqueado"]:
            raise HTTPException(403, f"El caso del detective se abre con {prog['racha_para_detective']} casos seguidos bien revisados")
    return sesion.abrir(d.seudonimo, caso_id, mid)


@app.post("/api/intento/{intento_id}/responder")
def responder(intento_id: int, d: ResponderIn, x_alumno: str = Header(default="")):
    _intento_de(intento_id, x_alumno)
    try:
        r = sesion.responder(intento_id, d.clave, d.confianza, d.justificacion)
    except (ValueError, KeyError, TypeError) as e:
        _err(e)
    r.pop("hechos", None)
    return r


@app.post("/api/intento/{intento_id}/revisar")
def revisar(intento_id: int, d: RevisarIn, x_alumno: str = Header(default="")):
    _intento_de(intento_id, x_alumno)
    try:
        r = sesion.revisar(intento_id, d.clave, d.confianza)
    except (ValueError, KeyError, TypeError) as e:
        _err(e)
    r.pop("hechos", None)
    return r


@app.post("/api/intento/{intento_id}/reflexion")
def reflexion(intento_id: int, d: TextoIn, x_alumno: str = Header(default="")):
    _intento_de(intento_id, x_alumno)
    try:
        return sesion.reflexionar(intento_id, d.texto)
    except ValueError as e:
        _err(e)


@app.post("/api/intento/{intento_id}/duda")
def duda(intento_id: int, x_alumno: str = Header(default="")):
    _intento_de(intento_id, x_alumno)
    return sesion.reportar_duda(intento_id)


@app.get("/api/tablero")
def tablero(grupo: Optional[str] = None, mapa: Optional[int] = None):
    if grupo:
        g = historial.grupo(grupo)
        if not g:
            raise HTTPException(404, "Grupo no existe")
        m = historial.mapa(mapa) if mapa else None
        return {"grupo": {"codigo": g["codigo"], "nombre": g["nombre"]}, "mapa": m,
                "mapas": historial.mapas_de_grupo(g["codigo"]),
                "equipos": historial.tablero_equipos_grupo(g["codigo"], m["id"] if m else None)}
    return {"grupo": None, "equipos": historial.tablero_equipos()}


@app.get("/api/universo/{codigo}")
def universo(codigo: str):
    """Vista global del grupo: territorios por mapa (materia) y totales por equipo."""
    todos, _ = motor.cargar_casos()
    u = historial.universo(codigo, {c["id"]: c["mision"] for c in todos.values()},
                           [c["id"] for c in todos.values() if c.get("especial") == "detective"])
    if not u:
        raise HTTPException(404, "Grupo no existe")
    u["misiones"] = [{"n": m["n"], "nombre": m["nombre"]} for m in META["misiones"]]
    return u


# =====================================================================
# Sesión docente
# =====================================================================
@app.post("/api/docente/login")
def docente_login(d: LoginIn):
    u = d.usuario.strip().lower()
    if historial.login_bloqueado(u):
        raise HTTPException(429, "Demasiados intentos. Espera un minuto")
    s = historial.login_docente(d.usuario, d.password)
    if not s:
        historial.registrar_fallo_login(u)
        raise HTTPException(401, "Usuario o contraseña incorrectos")
    historial.limpiar_fallos_login(u)
    return s


@app.post("/api/docente/logout")
def docente_logout(x_sesion: str = Header(default="")):
    historial.cerrar_sesion(x_sesion)
    return {"ok": True}


@app.get("/api/docente/yo")
def docente_yo(x_admin: str = Header(default=""), x_sesion: str = Header(default="")):
    q = _quien(x_admin, x_sesion)
    return {"admin": q.admin, "usuario": q.usuario, "nombre": "Administrador" if q.admin else q.docente["nombre"],
            "grupos": historial.grupos_de(None if q.admin else q.usuario)}


@app.post("/api/docente/grupos")
def crear_grupo(d: GrupoIn, x_admin: str = Header(default=""), x_sesion: str = Header(default="")):
    q = _quien(x_admin, x_sesion)
    if q.admin:
        raise HTTPException(400, "El administrador no tiene grupos propios; inicia sesión como docente")
    if len(d.nombre.strip()) < 1:
        raise HTTPException(400, "Escribe un nombre")
    return historial.crear_grupo(q.usuario, d.nombre, d.nivel or 2)


@app.put("/api/docente/grupos/{codigo}")
def renombrar_grupo(codigo: str, d: GrupoIn, x_admin: str = Header(default=""), x_sesion: str = Header(default="")):
    q = _quien(x_admin, x_sesion)
    if not q.puede_grupo(codigo):
        raise HTTPException(403, "Ese grupo no es tuyo")
    historial.renombrar_grupo(codigo, d.nombre, d.nivel)
    return {"ok": True}


@app.post("/api/docente/grupos/unirse")
def unirse_grupo(d: UnirseIn, x_admin: str = Header(default=""), x_sesion: str = Header(default="")):
    """Otro profesor se une a un grupo existente con su código para crear su propio mapa."""
    q = _quien(x_admin, x_sesion)
    if q.admin:
        raise HTTPException(400, "El administrador ya ve todos los grupos")
    try:
        g = historial.unirse_grupo(q.usuario, d.codigo)
    except ValueError as e:
        _err(e)
    return {"ok": True, "codigo": g["codigo"], "nombre": g["nombre"]}


@app.post("/api/docente/mapas")
def crear_mapa(d: MapaIn, x_admin: str = Header(default=""), x_sesion: str = Header(default="")):
    q = _quien(x_admin, x_sesion)
    if q.admin:
        raise HTTPException(400, "Los mapas los crea cada profesor desde su cuenta")
    if not d.codigo or not q.puede_grupo(d.codigo):
        raise HTTPException(403, "Primero únete a ese grupo")
    if len(d.nombre.strip()) < 2:
        raise HTTPException(400, "Escribe el nombre de la materia o tema")
    return historial.crear_mapa(d.codigo, q.usuario, d.nombre)


@app.put("/api/docente/mapas/{mapa_id}")
def renombrar_mapa(mapa_id: int, d: MapaIn, x_admin: str = Header(default=""), x_sesion: str = Header(default="")):
    q = _quien(x_admin, x_sesion)
    if not q.puede_mapa(mapa_id, solo_propio=True):
        raise HTTPException(403, "Ese mapa no es tuyo")
    historial.renombrar_mapa(mapa_id, d.nombre)
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
            c = dict(c, mapas=historial.mapas_del_caso(c["id"])); out.append(c)
    return out


@app.get("/api/docente/casos")
def docente_casos(x_admin: str = Header(default=""), x_sesion: str = Header(default="")):
    return _casos_de(_quien(x_admin, x_sesion))


@app.post("/api/docente/casos/{caso_id}/aprobar")
def docente_aprobar(caso_id: str, d: AprobarIn, x_admin: str = Header(default=""), x_sesion: str = Header(default="")):
    """Quita la marca provisional y asigna el caso a los mapas indicados."""
    q = _quien(x_admin, x_sesion)
    for m in d.mapas:
        if not q.puede_mapa(m, solo_propio=True):
            raise HTTPException(403, f"El mapa {m} no es tuyo")
    for f in (motor.CASOS_DIR / "docente").glob("*.json"):
        data = json.loads(f.read_text(encoding="utf-8"))
        for c in data.get("casos", []):
            if c["id"] == caso_id:
                if not q.admin and c.get("docente") != q.usuario:
                    raise HTTPException(403, "Ese caso no es tuyo")
                c["provisional"] = False
                c["revisado_por_docente"] = True
                f.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                historial.asignar_caso(caso_id, d.mapas)
                return {"ok": True, "mapas": d.mapas}
    raise HTTPException(404, "Caso no está en la carpeta docente")


def _caso_es_de(q: Quien, caso_id: str):
    todos, _ = motor.cargar_casos()
    c = todos.get(caso_id)
    if not c or not ("generado_por" in c or c.get("origen")):
        raise HTTPException(404, "Solo se asignan casos generados")
    if not q.admin and c.get("docente") != q.usuario:
        raise HTTPException(403, "Ese caso no es tuyo")


@app.put("/api/docente/casos/{caso_id}/mapas")
def docente_asignar(caso_id: str, d: AprobarIn, x_admin: str = Header(default=""), x_sesion: str = Header(default="")):
    q = _quien(x_admin, x_sesion)
    _caso_es_de(q, caso_id)
    for m in d.mapas:
        if not q.puede_mapa(m, solo_propio=True):
            raise HTTPException(403, f"El mapa {m} no es tuyo")
    historial.asignar_caso(caso_id, d.mapas)
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
    q = _quien(x_admin, x_sesion)
    if not historial.intento_de_grupos(d.intento_id, q.codigos()):
        raise HTTPException(403, "Ese intento no es de tus grupos")
    if not 0 <= d.puntaje <= 10:
        raise HTTPException(400, "puntaje fuera de rango")
    historial.guardar_revision(d.intento_id, d.puntaje, d.nota.strip()[:1000])
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
    historial.otorgar_insignia(d.seudonimo, d.postulado, q.usuario, _mapa_de(d.seudonimo, d.mapa))
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
    lista = historial.lista_alumnos_codigos(q.codigos())
    tr = historial.transferencias_de([a["seudonimo"] for a in lista])
    for a in lista:
        a["transferencia"] = {str(k): v for k, v in tr.get(a["seudonimo"], {}).items()}
    return lista


@app.put("/api/docente/alumnos/{seudonimo}/transferencia")
def docente_transferencia(seudonimo: str, d: TransferenciaIn, x_admin: str = Header(default=""), x_sesion: str = Header(default="")):
    """El docente marca si el alumno aplicó la habilidad en la tarea real (la investigación) de ese mapa."""
    q = _quien(x_admin, x_sesion)
    cod = historial.grupo_de_alumno(seudonimo)
    m = historial.mapa(d.mapa)
    if not cod or not q.puede_grupo(cod) or not m or m["codigo"] != cod:
        raise HTTPException(403, "Ese alumno o ese mapa no son de tus grupos")
    historial.marcar_transferencia(seudonimo, d.mapa, d.aplico, d.nota, q.usuario)
    return {"ok": True}


@app.get("/api/docente/transferencia")
def docente_resumen_transferencia(x_admin: str = Header(default=""), x_sesion: str = Header(default="")):
    q = _quien(x_admin, x_sesion)
    return historial.resumen_transferencia(q.codigos())


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
    posts = d.postulados or ([d.postulado] if d.postulado else [])
    if not posts or len(posts) > 4 or any(p not in generador.POSTULADOS for p in posts):
        raise HTTPException(400, "elige entre 1 y 4 postulados válidos")
    try:
        total = {"aceptados": [], "rechazados": [], "archivo": None}
        for p in posts:
            r = generador.generar(d.tema.strip(), d.nivel, p, d.formato, d.n, docente=q.usuario)
            total["aceptados"] += r["aceptados"]; total["rechazados"] += r["rechazados"]; total["archivo"] = r["archivo"]
        return total
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"Error llamando al modelo: {e}")


@app.put("/api/docente/casos/{caso_id}")
def docente_editar_caso(caso_id: str, d: CasoEditIn, x_admin: str = Header(default=""), x_sesion: str = Header(default="")):
    q = _quien(x_admin, x_sesion)
    permitidos = {"titulo", "situacion", "pregunta", "opciones", "pista", "explicacion", "reflexion", "rubrica_reflexion"}
    cambios = {k: v for k, v in d.cambios.items() if k in permitidos}
    try:
        r = generador.actualizar_caso(caso_id, cambios, solo_de=None if q.admin else q.usuario)
        todos, familias = motor.cargar_casos()
        motivos = generador.validar(todos[caso_id], familias) if caso_id in todos else []
        if isinstance(r, dict):
            r["avisos"] = motivos
        return r
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
    q = _quien(x_admin, x_sesion)
    return historial.alerta_casos(q.codigos())


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
