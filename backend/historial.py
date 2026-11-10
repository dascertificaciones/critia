"""
historial.py — Critia
Historial local en SQLite. Guarda alumnos (seudónimo + equipo), intentos por caso,
sentidos ganados e insignias asignadas por el docente.
"""
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

# Ruta de la base de datos. Se puede cambiar con la variable de entorno SEXTO_DB.
DB = Path(os.environ.get("SEXTO_DB", Path(__file__).parent / "historial.db"))
EQUIPOS = ["rojo", "azul", "verde", "violeta"]

ESQUEMA = """
CREATE TABLE IF NOT EXISTS alumnos (
    seudonimo TEXT PRIMARY KEY,
    equipo    TEXT NOT NULL,
    creado    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS intentos (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    seudonimo     TEXT NOT NULL,
    caso_id       TEXT NOT NULL,
    familia_caso  TEXT,
    inicio        TEXT NOT NULL,
    cierre        TEXT,
    -- fase inicial
    clave_ini     TEXT, conf_ini INTEGER, just_ini TEXT, eval_ini TEXT, tipo_error_ini TEXT,
    accion_ini    TEXT, motivo_ini TEXT,
    -- fase final
    clave_fin     TEXT, conf_fin INTEGER, eval_fin TEXT, tipo_error_fin TEXT,
    accion_fin    TEXT, motivo_fin TEXT,
    reflexion     TEXT,
    reporta_duda  INTEGER DEFAULT 0,
    sentidos      TEXT,          -- JSON: ["justificar","revisar","calibrar"]
    diagnosticos  TEXT           -- JSON
);
CREATE TABLE IF NOT EXISTS insignias (
    seudonimo TEXT NOT NULL,
    postulado INTEGER NOT NULL,
    otorgada  TEXT NOT NULL,
    por       TEXT,
    PRIMARY KEY (seudonimo, postulado)
);
CREATE TABLE IF NOT EXISTS revision_docente (
    intento_id INTEGER PRIMARY KEY,
    puntaje    INTEGER,
    nota       TEXT,
    fecha      TEXT
);
"""


def conectar():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.executescript(ESQUEMA)
    return con


def ahora():
    return datetime.now().isoformat(timespec="seconds")


# ---------- Alumnos ----------
import re as _re
SEUDONIMO_RE = _re.compile(r"^[A-Za-z0-9ÁÉÍÓÚáéíóúÑñ_\-]{3,24}$")


def registrar_alumno(seudonimo, equipo):
    seudonimo = (seudonimo or "").strip()
    if not SEUDONIMO_RE.match(seudonimo):
        raise ValueError("El seudónimo lleva de 3 a 24 letras o números, sin espacios ni símbolos")
    equipo = equipo.lower()
    if equipo not in EQUIPOS:
        raise ValueError(f"Equipo inválido: {equipo}")
    with conectar() as con:
        con.execute("INSERT OR IGNORE INTO alumnos (seudonimo, equipo, creado) VALUES (?,?,?)", (seudonimo, equipo, ahora()))
        return dict(con.execute("SELECT * FROM alumnos WHERE seudonimo=?", (seudonimo,)).fetchone())


def obtener_alumno(seudonimo):
    with conectar() as con:
        r = con.execute("SELECT * FROM alumnos WHERE seudonimo=?", (seudonimo,)).fetchone()
        return dict(r) if r else None


# ---------- Intentos ----------
def abrir_intento(seudonimo, caso_id, familia_caso, mapa_id=None):
    """Abre un intento. Si el alumno ya cerró ese caso en ese mapa, el nuevo intento es una repetición:
    sirve para practicar pero no suma sentidos, racha, insignias ni territorio."""
    with conectar() as con:
        ya = con.execute("SELECT 1 FROM intentos WHERE seudonimo=? AND caso_id=? AND cierre IS NOT NULL AND (mapa_id IS ? OR ?)",
                         (seudonimo, caso_id, mapa_id, mapa_id is None)).fetchone()
        cur = con.execute(
            "INSERT INTO intentos (seudonimo, caso_id, familia_caso, inicio, mapa_id, repeticion) VALUES (?,?,?,?,?,?)",
            (seudonimo, caso_id, familia_caso, ahora(), mapa_id, 1 if ya else 0))
        return cur.lastrowid


def intento_abierto(seudonimo, caso_id, mapa_id=None):
    """Intento sin cerrar para ese alumno, caso y mapa (permite retomar)."""
    with conectar() as con:
        r = con.execute(
            "SELECT * FROM intentos WHERE seudonimo=? AND caso_id=? AND cierre IS NULL AND (mapa_id IS ? OR ?) ORDER BY id DESC LIMIT 1",
            (seudonimo, caso_id, mapa_id, mapa_id is None)).fetchone()
        return dict(r) if r else None


def guardar_inicial(intento_id, clave, conf, just, eval_, tipo_error, accion, motivo):
    with conectar() as con:
        con.execute("""UPDATE intentos SET clave_ini=?, conf_ini=?, just_ini=?, eval_ini=?, tipo_error_ini=?,
                       accion_ini=?, motivo_ini=? WHERE id=?""",
                    (clave, conf, just, eval_, tipo_error, accion, motivo, intento_id))


def guardar_final(intento_id, clave, conf, eval_, tipo_error, accion, motivo, sentidos, diagnosticos):
    with conectar() as con:
        con.execute("""UPDATE intentos SET clave_fin=?, conf_fin=?, eval_fin=?, tipo_error_fin=?,
                       accion_fin=?, motivo_fin=?, sentidos=?, diagnosticos=?, cierre=? WHERE id=?""",
                    (clave, conf, eval_, tipo_error, accion, motivo,
                     json.dumps(sentidos), json.dumps(diagnosticos), ahora(), intento_id))


def guardar_pista(intento_id, nivel, pedida=False):
    """Registra que el alumno recibió la pista de ese nivel (1 suave, 2 fuerte)."""
    with conectar() as con:
        con.execute("UPDATE intentos SET pistas_usadas=MAX(COALESCE(pistas_usadas,0), ?), pista_pedida=MAX(COALESCE(pista_pedida,0), ?) WHERE id=?",
                    (int(nivel), 1 if pedida else 0, intento_id))


def guardar_media(intento_id, clave, conf):
    """Segunda decisión cuando todavía hay una pista más por dar."""
    with conectar() as con:
        con.execute("UPDATE intentos SET clave_med=?, conf_med=? WHERE id=?", (clave, conf, intento_id))


def fallo_mision_previa(seudonimo, mapa_id, mision_de_caso, mision):
    """True si el último caso cerrado de esa misión (en ese mapa) terminó en error."""
    with conectar() as con:
        rows = con.execute("""SELECT caso_id, eval_fin FROM intentos WHERE seudonimo=? AND cierre IS NOT NULL
                              AND (mapa_id IS ? OR ?) ORDER BY cierre DESC""", (seudonimo, mapa_id, mapa_id is None)).fetchall()
        for r in rows:
            if mision_de_caso.get(r["caso_id"]) == mision:
                return r["eval_fin"] not in (None, "correcta", "abierta")
        return False


def puntos_territorio(sentidos, eval_fin, pistas, armadura=0):
    """Puntos que un intento cerrado aporta al territorio de su equipo:
    uno por cada habilidad ganada, uno por resolver sin ayuda y uno si la armadura resistió.
    `pistas` son las ayudas que cuentan: la pregunta de «revisar primero» no es ayuda."""
    return len(sentidos) + (1 if (eval_fin == "correcta" and (pistas or 0) <= 0) else 0) + (armadura or 0)


# SQL de las ayudas que cuentan y del punto de armadura (i = intentos)
SQL_PUNTOS = "(COALESCE(i.pistas_usadas,0) - COALESCE(i.reviso_antes,0)) pistas, COALESCE(i.punto_armadura,0) arm, i.armadura armadura"


def resultado_armadura(eval_ini, conf_ini):
    """La seguridad inicial puesta a prueba con la primera respuesta.
    resiste: seguro y acertó (+1). abollada: seguro y falló (corta la racha).
    ligera: dudó y acertó. protegido: dudó y falló (conserva la racha)."""
    alta, acerto = (conf_ini or 0) >= SEGURO_DESDE, eval_ini == "correcta"
    return ("resiste" if acerto else "abollada") if alta else ("ligera" if acerto else "protegido")


def guardar_armadura(intento_id, armadura):
    with conectar() as con:
        con.execute("UPDATE intentos SET armadura=?, punto_armadura=? WHERE id=?", (armadura, 1 if armadura == "resiste" else 0, intento_id))


def marcar_reviso(intento_id):
    """El alumno usó «revisar primero» antes de decidir. No cuenta como ayuda."""
    with conectar() as con:
        con.execute("UPDATE intentos SET reviso_antes=1 WHERE id=?", (intento_id,))


def efecto_racha(sentidos, eval_ini, armadura=None):
    """Qué hace un caso cerrado con la racha: 1 la sube, 0 la conserva, -1 la corta.
    Los intentos anteriores a la armadura (armadura None) siguen la regla de antes."""
    if armadura == "abollada":
        return -1
    if eval_ini == "correcta" or "revisar" in sentidos:
        return 1
    return 0 if armadura == "protegido" else -1


def resolucion(it):
    """Etiqueta legible de cómo terminó el intento, para el docente."""
    if it.get("eval_fin") == "abierta":
        return "abierta"
    if it.get("eval_fin") != "correcta":
        return "no_resolvio"
    p, reviso = it.get("pistas_usadas") or 0, it.get("reviso_antes") or 0
    if p - reviso <= 0:
        return "reviso" if reviso else "solo"
    return "con_pregunta" if (p == 1 and not reviso) else "con_senalamiento"


def guardar_reflexion(intento_id, texto):
    with conectar() as con:
        con.execute("UPDATE intentos SET reflexion=? WHERE id=?", (texto, intento_id))


def marcar_duda(intento_id):
    with conectar() as con:
        con.execute("UPDATE intentos SET reporta_duda=1 WHERE id=?", (intento_id,))


def obtener_intento(intento_id):
    with conectar() as con:
        r = con.execute("SELECT * FROM intentos WHERE id=?", (intento_id,)).fetchone()
        return dict(r) if r else None


# ---------- Consultas para el motor ----------
def errores_previos(seudonimo):
    """familia -> cantidad de casos cerrados con error inicial de esa familia."""
    with conectar() as con:
        rows = con.execute("""SELECT tipo_error_ini, COUNT(*) n FROM intentos
                              WHERE seudonimo=? AND cierre IS NOT NULL AND tipo_error_ini IS NOT NULL
                              GROUP BY tipo_error_ini""", (seudonimo,)).fetchall()
        return {r["tipo_error_ini"]: r["n"] for r in rows}


# ---------- Consultas para el juego ----------
SEGURO_DESDE = 60          # seguridad desde la que cuenta como «seguro» (niveles 75 y 100 de la armadura)
RETO_POR_JUGADOR = 3       # casos bien revisados por jugador que forman el reto semanal del equipo
RETO_MINIMO = 6            # meta mínima del reto semanal, para equipos pequeños
META_DIARIA = 3            # casos nuevos que forman la «misión de hoy» del alumno
RACHA_PARA_DETECTIVE = 3   # casos seguidos "bien revisados" para desbloquear el caso del detective
CASOS_PARA_INSIGNIA = 2    # casos del mismo postulado sin pista para sugerir insignia




def progreso_alumno(seudonimo, casos_por_postulado=None, mapa_id=None):
    """Progreso del alumno. Con mapa_id, solo los intentos e insignias de ese mapa."""
    fm = " AND mapa_id=?" if mapa_id else ""
    pm = (mapa_id,) if mapa_id else ()
    with conectar() as con:
        rows = con.execute(f"""SELECT i.caso_id, i.sentidos, i.eval_ini, i.eval_fin, i.cierre, i.conf_ini, COALESCE(i.reviso_antes,0) reviso, {SQL_PUNTOS} FROM intentos i
                              WHERE seudonimo=? AND cierre IS NOT NULL AND COALESCE(repeticion,0)=0{fm} ORDER BY cierre""",
                           (seudonimo,) + pm).fetchall()
        casos, total, racha, mejor_racha = {}, 0, 0, 0
        avance = {}
        puntos_total, hoy, casos_hoy, puntos_hoy = 0, ahora()[:10], [], 0
        # Puntería: ¿la seguridad inicial coincidió con el resultado de la primera respuesta?
        punteria = {"total": 0, "coinciden": 0, "seguro_y_mal": 0, "duda_y_bien": 0}
        # Revisión: cuántas veces revisó antes de decidir y cómo le fue a su armadura
        revision = {"casos": 0, "reviso_antes": 0, "abolladas": 0, "resistio": 0}
        for r in rows:
            if r["eval_ini"] in ("correcta", "error_esperado", "error_otro") and r["conf_ini"] is not None:
                acerto, seguro = r["eval_ini"] == "correcta", r["conf_ini"] >= SEGURO_DESDE
                punteria["total"] += 1
                punteria["coinciden"] += 1 if acerto == seguro else 0
                punteria["seguro_y_mal"] += 1 if (seguro and not acerto) else 0
                punteria["duda_y_bien"] += 1 if (acerto and not seguro) else 0
            s = json.loads(r["sentidos"] or "[]")
            pts = puntos_territorio(s, r["eval_fin"], r["pistas"], r["arm"])
            if r["eval_ini"] in ("correcta", "error_esperado", "error_otro"):
                revision["casos"] += 1
                revision["reviso_antes"] += r["reviso"]
                revision["abolladas"] += 1 if r["armadura"] == "abollada" else 0
                revision["resistio"] += 1 if r["armadura"] == "resiste" else 0
            casos[r["caso_id"]] = {"sentidos": s, "eval_ini": r["eval_ini"], "eval_fin": r["eval_fin"], "puntos": pts}
            total += len(s)
            puntos_total += pts
            if (r["cierre"] or "")[:10] == hoy:
                casos_hoy.append(r["caso_id"])
                puntos_hoy += pts
            ef = efecto_racha(s, r["eval_ini"], r["armadura"])
            if ef > 0:
                racha += 1
                mejor_racha = max(mejor_racha, racha)
            elif ef < 0:
                racha = 0
            if casos_por_postulado and r["eval_ini"] == "correcta":
                p = casos_por_postulado.get(r["caso_id"])
                if p:
                    avance.setdefault(str(p), set()).add(r["caso_id"])
        ins = [r["postulado"] for r in con.execute(f"SELECT postulado FROM insignias WHERE seudonimo=?{fm}", (seudonimo,) + pm)]
        n_av = con.execute(f"SELECT COUNT(*) FROM avances WHERE seudonimo=? AND estado='aceptado'{fm}", (seudonimo,) + pm).fetchone()[0]
        puntos_total += n_av * PUNTOS_AVANCE
        return {
            "casos": casos,
            "sentidos_total": total,
            "puntos_total": puntos_total,
            "avances_aceptados": n_av,
            "casos_hoy": casos_hoy,
            "puntos_hoy": puntos_hoy,
            "meta_diaria": META_DIARIA,
            "punteria": punteria,
            "revision": revision,
            "insignias": ins,
            "avance_insignias": {p: len(v) for p, v in avance.items()},
            "casos_para_insignia": CASOS_PARA_INSIGNIA,
            "racha": racha,
            "mejor_racha": mejor_racha,
            "racha_para_detective": RACHA_PARA_DETECTIVE,
            "detective_desbloqueado": mejor_racha >= RACHA_PARA_DETECTIVE,
        }


def tablero_equipos():
    with conectar() as con:
        tab = {e: {"sentidos": 0, "casos": 0, "alumnos": 0, "insignias": 0, "justificar": 0, "revisar": 0, "calibrar": 0}
               for e in EQUIPOS}
        for r in con.execute("SELECT equipo, COUNT(*) n FROM alumnos GROUP BY equipo"):
            tab[r["equipo"]]["alumnos"] = r["n"]
        rows = con.execute("""SELECT a.equipo, i.sentidos FROM intentos i JOIN alumnos a ON a.seudonimo=i.seudonimo
                              WHERE i.cierre IS NOT NULL""").fetchall()
        for r in rows:
            s = json.loads(r["sentidos"] or "[]")
            t = tab[r["equipo"]]
            t["sentidos"] += len(s)
            t["casos"] += 1
            for k in s:
                if k in t:
                    t[k] += 1
        for r in con.execute("SELECT a.equipo, COUNT(*) n FROM insignias i JOIN alumnos a ON a.seudonimo=i.seudonimo GROUP BY a.equipo"):
            tab[r["equipo"]]["insignias"] = r["n"]
        return tab


# ---------- Docente ----------
def otorgar_insignia(seudonimo, postulado, por="docente", mapa_id=None):
    with conectar() as con:
        con.execute("INSERT OR REPLACE INTO insignias (seudonimo, postulado, mapa_id, otorgada, por) VALUES (?,?,?,?,?)",
                    (seudonimo, postulado, mapa_id or 0, ahora(), por))


def sugerencias_insignia(casos_por_postulado):
    """Alumnos con CASOS_PARA_INSIGNIA+ casos del mismo postulado correctos sin pista (eval_ini correcta)."""
    with conectar() as con:
        rows = con.execute("SELECT seudonimo, caso_id FROM intentos WHERE cierre IS NOT NULL AND eval_ini='correcta'").fetchall()
        conteo = {}
        for r in rows:
            p = casos_por_postulado.get(r["caso_id"])
            if p is None:
                continue
            conteo.setdefault((r["seudonimo"], p), set()).add(r["caso_id"])
        ya = {(r["seudonimo"], r["postulado"]) for r in con.execute("SELECT seudonimo, postulado FROM insignias")}
        return [{"seudonimo": k[0], "postulado": k[1], "casos": sorted(v)}
                for k, v in conteo.items() if len(v) >= CASOS_PARA_INSIGNIA and k not in ya]


def reflexiones_pendientes():
    with conectar() as con:
        rows = con.execute("""SELECT i.id, i.seudonimo, i.caso_id, i.reflexion, i.cierre FROM intentos i
                              LEFT JOIN revision_docente r ON r.intento_id=i.id
                              WHERE i.reflexion IS NOT NULL AND i.reflexion<>'' AND r.intento_id IS NULL
                              ORDER BY i.cierre""").fetchall()
        return [dict(r) for r in rows]


def guardar_revision(intento_id, puntaje, nota):
    with conectar() as con:
        con.execute("INSERT OR REPLACE INTO revision_docente VALUES (?,?,?,?)", (intento_id, puntaje, nota, ahora()))


def alerta_casos(codigos=None):
    """Casos donde más del 80% mantiene el error tras la pista, o nadie se equivoca. Filtrado por grupos."""
    f, params = _filtro_grupos(codigos)
    with conectar() as con:
        rows = con.execute(f"""SELECT i.caso_id,
                                COUNT(*) n,
                                SUM(i.eval_ini<>'correcta') err_ini,
                                SUM(i.eval_ini<>'correcta' AND i.eval_fin<>'correcta') err_fin,
                                SUM(i.reporta_duda) dudas
                              FROM intentos i JOIN alumnos a ON a.seudonimo=i.seudonimo WHERE i.cierre IS NOT NULL{f} GROUP BY i.caso_id""", params).fetchall()
        alertas = []
        for r in rows:
            if r["n"] < 5:
                continue
            if r["err_ini"] and r["err_fin"] / r["err_ini"] > 0.8:
                alertas.append({"caso_id": r["caso_id"], "tipo": "pista_no_funciona_o_clave_mal", "n": r["n"]})
            if r["err_ini"] == 0:
                alertas.append({"caso_id": r["caso_id"], "tipo": "demasiado_facil", "n": r["n"]})
            if r["dudas"] >= 3:
                alertas.append({"caso_id": r["caso_id"], "tipo": "alumnos_reportan_duda", "n": r["dudas"]})
        return alertas


# ---------- Docente: vista de grupo ----------
def resumen_grupo():
    """Resumen por caso y por familia de error, sin nombres."""
    with conectar() as con:
        por_caso = [dict(r) for r in con.execute("""
            SELECT caso_id, COUNT(*) n,
                   SUM(eval_ini='correcta') ok_ini,
                   SUM(eval_ini<>'correcta' AND eval_fin='correcta') mejoraron,
                   SUM(eval_ini<>'correcta' AND eval_fin<>'correcta') siguen_mal,
                   ROUND(AVG(conf_ini)) conf_ini_prom, ROUND(AVG(conf_fin)) conf_fin_prom,
                   SUM(reporta_duda) dudas
            FROM intentos WHERE cierre IS NOT NULL GROUP BY caso_id ORDER BY caso_id""")]
        por_familia = [dict(r) for r in con.execute("""
            SELECT tipo_error_ini familia, COUNT(*) n FROM intentos
            WHERE cierre IS NOT NULL AND tipo_error_ini IS NOT NULL GROUP BY tipo_error_ini ORDER BY n DESC""")]
        totales = dict(con.execute("""
            SELECT COUNT(DISTINCT seudonimo) alumnos, COUNT(*) intentos,
                   SUM(eval_ini<>'correcta' AND eval_fin='correcta') mejoraron,
                   SUM(eval_ini<>'correcta') errores_ini
            FROM intentos WHERE cierre IS NOT NULL""").fetchone())
        return {"totales": totales, "por_caso": por_caso, "por_familia": por_familia}


def lista_alumnos():
    with conectar() as con:
        rows = con.execute("""
            SELECT a.seudonimo, a.equipo, COUNT(i.id) casos,
                   COALESCE(SUM(LENGTH(i.sentidos) - LENGTH(REPLACE(i.sentidos, ',', '')) + (i.sentidos <> '[]')), 0) sentidos,
                   (SELECT COUNT(*) FROM insignias x WHERE x.seudonimo=a.seudonimo) insignias
            FROM alumnos a LEFT JOIN intentos i ON i.seudonimo=a.seudonimo AND i.cierre IS NOT NULL
            GROUP BY a.seudonimo ORDER BY a.equipo, a.seudonimo""").fetchall()
        return [dict(r) for r in rows]


def historial_alumno(seudonimo):
    with conectar() as con:
        rows = con.execute("""SELECT id, caso_id, inicio, clave_ini, conf_ini, just_ini, eval_ini, tipo_error_ini, accion_ini,
                              clave_med, conf_med, clave_fin, conf_fin, eval_fin, accion_fin, motivo_fin, sentidos, reflexion, reporta_duda,
                              COALESCE(pistas_usadas,0) pistas_usadas, COALESCE(pista_pedida,0) pista_pedida, COALESCE(repeticion,0) repeticion
                              FROM intentos WHERE seudonimo=? AND cierre IS NOT NULL ORDER BY inicio""", (seudonimo,)).fetchall()
        out = []
        for r in rows:
            d = dict(r); d["sentidos"] = json.loads(d["sentidos"] or "[]"); d["resolucion"] = resolucion(d); out.append(d)
        return out


# =====================================================================
# Docentes y grupos
# =====================================================================
import hashlib, secrets, string

ESQUEMA_V2 = """
CREATE TABLE IF NOT EXISTS docentes (
    usuario   TEXT PRIMARY KEY,
    nombre    TEXT NOT NULL,
    hash      TEXT NOT NULL,
    sal       TEXT NOT NULL,
    creado    TEXT NOT NULL,
    activo    INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS grupos (
    codigo    TEXT PRIMARY KEY,
    nombre    TEXT NOT NULL,
    docente   TEXT NOT NULL,
    creado    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sesiones_docente (
    token     TEXT PRIMARY KEY,
    usuario   TEXT NOT NULL,
    creado    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS casos_grupo (
    caso_id   TEXT NOT NULL,
    codigo    TEXT NOT NULL,
    PRIMARY KEY (caso_id, codigo)
);
"""


ESQUEMA_V3 = """
CREATE TABLE IF NOT EXISTS docentes_grupo (
    usuario   TEXT NOT NULL,
    codigo    TEXT NOT NULL,
    PRIMARY KEY (usuario, codigo)
);
CREATE TABLE IF NOT EXISTS mapas (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo    TEXT NOT NULL,
    docente   TEXT NOT NULL,
    nombre    TEXT NOT NULL,
    creado    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS casos_mapa (
    caso_id   TEXT NOT NULL,
    mapa_id   INTEGER NOT NULL,
    PRIMARY KEY (caso_id, mapa_id)
);
CREATE TABLE IF NOT EXISTS transferencias (
    seudonimo TEXT NOT NULL,
    mapa_id   INTEGER NOT NULL,
    aplico    INTEGER NOT NULL DEFAULT 0,
    nota      TEXT,
    docente   TEXT,
    fecha     TEXT,
    PRIMARY KEY (seudonimo, mapa_id)
);
CREATE TABLE IF NOT EXISTS tareas (
    mapa_id   INTEGER PRIMARY KEY,
    tipo      TEXT NOT NULL,
    tema      TEXT NOT NULL,
    alcances  TEXT,
    consigna  TEXT NOT NULL,
    pasos     TEXT NOT NULL,          -- JSON: [{mision, titulo, instruccion, entregable}]
    aprobada  INTEGER NOT NULL DEFAULT 0,
    creado    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS avances (
    seudonimo TEXT NOT NULL,
    mapa_id   INTEGER NOT NULL,
    mision    INTEGER NOT NULL,
    texto     TEXT NOT NULL,
    enviado   TEXT NOT NULL,
    estado    TEXT NOT NULL DEFAULT 'pendiente',   -- pendiente | aceptado | devuelto
    nota      TEXT,
    docente   TEXT,
    revisado  TEXT,
    PRIMARY KEY (seudonimo, mapa_id, mision)
);
CREATE TABLE IF NOT EXISTS sesiones_alumno (
    token     TEXT PRIMARY KEY,
    seudonimo TEXT NOT NULL,
    creado    TEXT NOT NULL
);
"""


def _migrar():
    with conectar() as con:
        con.executescript(ESQUEMA_V2)
        cols = [r[1] for r in con.execute("PRAGMA table_info(alumnos)")]
        if "grupo" not in cols:
            con.execute("ALTER TABLE alumnos ADD COLUMN grupo TEXT")
        cols = [r[1] for r in con.execute("PRAGMA table_info(grupos)")]
        if "nivel" not in cols:
            con.execute("ALTER TABLE grupos ADD COLUMN nivel INTEGER DEFAULT 2")
        # ---- V3: grupos compartidos, mapas por docente, territorio ----
        con.executescript(ESQUEMA_V3)
        cols = [r[1] for r in con.execute("PRAGMA table_info(intentos)")]
        if "mapa_id" not in cols:
            con.execute("ALTER TABLE intentos ADD COLUMN mapa_id INTEGER")
        if "repeticion" not in cols:
            con.execute("ALTER TABLE intentos ADD COLUMN repeticion INTEGER DEFAULT 0")
        for col, tipo in (("pistas_usadas", "INTEGER DEFAULT 0"), ("pista_pedida", "INTEGER DEFAULT 0"), ("clave_med", "TEXT"), ("conf_med", "INTEGER"),
                          ("reviso_antes", "INTEGER DEFAULT 0"), ("armadura", "TEXT"), ("punto_armadura", "INTEGER DEFAULT 0")):
            if col not in cols:
                con.execute(f"ALTER TABLE intentos ADD COLUMN {col} {tipo}")
        cols = [r[1] for r in con.execute("PRAGMA table_info(mapas)")]
        if "solo_propios" not in cols:
            con.execute("ALTER TABLE mapas ADD COLUMN solo_propios INTEGER DEFAULT 0")
        cols = [r[1] for r in con.execute("PRAGMA table_info(tareas)")]
        if "entrega" not in cols:
            con.execute("ALTER TABLE tareas ADD COLUMN entrega TEXT")
        cols = [r[1] for r in con.execute("PRAGMA table_info(insignias)")]
        if "mapa_id" not in cols:
            con.executescript("""
                CREATE TABLE insignias_v3 (
                    seudonimo TEXT NOT NULL, postulado INTEGER NOT NULL, mapa_id INTEGER NOT NULL DEFAULT 0,
                    otorgada TEXT NOT NULL, por TEXT, PRIMARY KEY (seudonimo, postulado, mapa_id));
                INSERT INTO insignias_v3 (seudonimo, postulado, mapa_id, otorgada, por)
                    SELECT seudonimo, postulado, 0, otorgada, por FROM insignias;
                DROP TABLE insignias; ALTER TABLE insignias_v3 RENAME TO insignias;""")
        con.execute("UPDATE alumnos SET equipo='violeta' WHERE equipo='amarillo'")
        # el creador de cada grupo es miembro
        con.execute("INSERT OR IGNORE INTO docentes_grupo SELECT docente, codigo FROM grupos")
        # cada grupo sin mapas recibe un mapa inicial y hereda sus casos, intentos e insignias
        for g in con.execute("SELECT codigo, docente FROM grupos").fetchall():
            if con.execute("SELECT 1 FROM mapas WHERE codigo=?", (g["codigo"],)).fetchone():
                continue
            cur = con.execute("INSERT INTO mapas (codigo, docente, nombre, creado) VALUES (?,?,?,?)",
                              (g["codigo"], g["docente"], "Expedición", ahora()))
            mid = cur.lastrowid
            con.execute("INSERT OR IGNORE INTO casos_mapa SELECT caso_id, ? FROM casos_grupo WHERE codigo=?", (mid, g["codigo"]))
            con.execute("""UPDATE intentos SET mapa_id=? WHERE mapa_id IS NULL AND seudonimo IN
                           (SELECT seudonimo FROM alumnos WHERE grupo=?)""", (mid, g["codigo"]))
            con.execute("""UPDATE insignias SET mapa_id=? WHERE mapa_id=0 AND seudonimo IN
                           (SELECT seudonimo FROM alumnos WHERE grupo=?)""", (mid, g["codigo"]))


_migrar()


def _hash(pw, sal):
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), sal.encode(), 120_000).hex()


# ---------- Docentes ----------
def crear_docente(usuario, nombre, password):
    usuario = usuario.strip().lower()
    if not usuario or not password or len(password) < 6:
        raise ValueError("Usuario y contraseña (mínimo 6 caracteres) son obligatorios")
    sal = secrets.token_hex(8)
    with conectar() as con:
        if con.execute("SELECT 1 FROM docentes WHERE usuario=?", (usuario,)).fetchone():
            raise ValueError("Ese usuario ya existe")
        con.execute("INSERT INTO docentes VALUES (?,?,?,?,?,1)", (usuario, nombre.strip(), _hash(password, sal), sal, ahora()))
    return {"usuario": usuario, "nombre": nombre.strip()}


def cambiar_password(usuario, password):
    if len(password) < 6:
        raise ValueError("Mínimo 6 caracteres")
    sal = secrets.token_hex(8)
    with conectar() as con:
        con.execute("UPDATE docentes SET hash=?, sal=? WHERE usuario=?", (_hash(password, sal), sal, usuario))
        con.execute("DELETE FROM sesiones_docente WHERE usuario=?", (usuario,))


def listar_docentes():
    with conectar() as con:
        return [dict(r) for r in con.execute("""SELECT d.usuario, d.nombre, d.creado, d.activo,
                    (SELECT COUNT(*) FROM docentes_grupo g WHERE g.usuario=d.usuario) grupos FROM docentes d ORDER BY d.nombre""")]


def activar_docente(usuario, activo):
    with conectar() as con:
        con.execute("UPDATE docentes SET activo=? WHERE usuario=?", (1 if activo else 0, usuario))
        if not activo:
            con.execute("DELETE FROM sesiones_docente WHERE usuario=?", (usuario,))


def login_docente(usuario, password):
    usuario = usuario.strip().lower()
    with conectar() as con:
        r = con.execute("SELECT * FROM docentes WHERE usuario=? AND activo=1", (usuario,)).fetchone()
        if not r or _hash(password, r["sal"]) != r["hash"]:
            return None
        token = secrets.token_urlsafe(24)
        con.execute("INSERT INTO sesiones_docente VALUES (?,?,?)", (token, usuario, ahora()))
        return {"token": token, "usuario": usuario, "nombre": r["nombre"]}


SESION_DOCENTE_HORAS = 12
_fallos_login = {}   # usuario -> [n_fallos, hasta_cuando]


def docente_por_token(token):
    if not token:
        return None
    with conectar() as con:
        r = con.execute("""SELECT d.usuario, d.nombre, s.creado FROM sesiones_docente s JOIN docentes d ON d.usuario=s.usuario
                           WHERE s.token=? AND d.activo=1""", (token,)).fetchone()
        if not r:
            return None
        if (datetime.now() - datetime.fromisoformat(r["creado"])).total_seconds() > SESION_DOCENTE_HORAS * 3600:
            con.execute("DELETE FROM sesiones_docente WHERE token=?", (token,))
            return None
        return {"usuario": r["usuario"], "nombre": r["nombre"]}


def login_bloqueado(usuario):
    f = _fallos_login.get(usuario)
    return bool(f and f[0] >= 5 and datetime.now() < f[1])


def registrar_fallo_login(usuario):
    from datetime import timedelta
    f = _fallos_login.setdefault(usuario, [0, datetime.now()])
    f[0] += 1
    if f[0] >= 5:
        f[1] = datetime.now() + timedelta(seconds=60)


def limpiar_fallos_login(usuario):
    _fallos_login.pop(usuario, None)


def intento_de_grupos(intento_id, codigos):
    """True si el intento pertenece a un alumno de alguno de esos grupos (None = cualquiera)."""
    with conectar() as con:
        r = con.execute("SELECT a.grupo FROM intentos i JOIN alumnos a ON a.seudonimo=i.seudonimo WHERE i.id=?", (intento_id,)).fetchone()
        if not r:
            return False
        return codigos is None or r["grupo"] in codigos


def cerrar_sesion(token):
    with conectar() as con:
        con.execute("DELETE FROM sesiones_docente WHERE token=?", (token,))


# ---------- Grupos ----------
def _codigo_grupo():
    alfabeto = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sin 0/O/1/I
    return "".join(secrets.choice(alfabeto) for _ in range(6))


def crear_grupo(docente, nombre, nivel=2):
    nivel = int(nivel) if int(nivel) in (1, 2, 3) else 2
    with conectar() as con:
        for _ in range(10):
            cod = _codigo_grupo()
            if not con.execute("SELECT 1 FROM grupos WHERE codigo=?", (cod,)).fetchone():
                break
        con.execute("INSERT INTO grupos (codigo, nombre, docente, creado, nivel) VALUES (?,?,?,?,?)",
                    (cod, nombre.strip(), docente, ahora(), nivel))
        con.execute("INSERT OR IGNORE INTO docentes_grupo VALUES (?,?)", (docente, cod))
        return {"codigo": cod, "nombre": nombre.strip(), "docente": docente, "nivel": nivel}


def grupos_de(docente=None):
    """Grupos del docente (por membresía). Sin docente: todos. Cada grupo trae sus mapas y profesores."""
    with conectar() as con:
        if docente:
            rows = con.execute("""SELECT g.*, (SELECT COUNT(*) FROM alumnos a WHERE a.grupo=g.codigo) alumnos
                        FROM grupos g JOIN docentes_grupo dg ON dg.codigo=g.codigo WHERE dg.usuario=? ORDER BY g.creado""", (docente,))
        else:
            rows = con.execute("""SELECT g.*, (SELECT COUNT(*) FROM alumnos a WHERE a.grupo=g.codigo) alumnos
                        FROM grupos g ORDER BY g.creado""")
        out = []
        for r in rows:
            g = dict(r)
            g["mapas"] = mapas_de_grupo(g["codigo"])
            g["profesores"] = [dict(x) for x in con.execute("""SELECT d.usuario, d.nombre FROM docentes_grupo dg
                        JOIN docentes d ON d.usuario=dg.usuario WHERE dg.codigo=? ORDER BY d.nombre""", (g["codigo"],))]
            out.append(g)
        return out


def unirse_grupo(docente, codigo):
    g = grupo(codigo)
    if not g:
        raise ValueError("Ese código de grupo no existe")
    with conectar() as con:
        con.execute("INSERT OR IGNORE INTO docentes_grupo VALUES (?,?)", (docente, g["codigo"]))
    return g


def es_miembro(docente, codigo):
    with conectar() as con:
        return bool(con.execute("SELECT 1 FROM docentes_grupo WHERE usuario=? AND codigo=?", (docente, (codigo or "").upper())).fetchone())


# ---------- Mapas (uno por docente/materia dentro de un grupo) ----------
def mapas_de_grupo(codigo):
    with conectar() as con:
        return [dict(r) for r in con.execute("""SELECT m.*, d.nombre docente_nombre,
                    (SELECT COUNT(*) FROM casos_mapa c WHERE c.mapa_id=m.id) casos_propios,
                    (SELECT t.tipo FROM tareas t WHERE t.mapa_id=m.id) tarea_tipo,
                    (SELECT t.aprobada FROM tareas t WHERE t.mapa_id=m.id) tarea_aprobada
                    FROM mapas m LEFT JOIN docentes d ON d.usuario=m.docente WHERE m.codigo=? ORDER BY m.creado""", (codigo,))]


def mapa(mapa_id):
    with conectar() as con:
        r = con.execute("SELECT * FROM mapas WHERE id=?", (mapa_id,)).fetchone()
        return dict(r) if r else None


def crear_mapa(codigo, docente, nombre):
    with conectar() as con:
        cur = con.execute("INSERT INTO mapas (codigo, docente, nombre, creado) VALUES (?,?,?,?)",
                          (codigo.upper(), docente, nombre.strip(), ahora()))
        con.commit()
        return dict(con.execute("SELECT * FROM mapas WHERE id=?", (cur.lastrowid,)).fetchone())


def renombrar_mapa(mapa_id, nombre):
    with conectar() as con:
        con.execute("UPDATE mapas SET nombre=? WHERE id=?", (nombre.strip(), mapa_id))


def fijar_solo_propios(mapa_id, valor):
    """Si es verdadero, el mapa muestra únicamente los casos aprobados que el docente le asignó (sin el banco base)."""
    with conectar() as con:
        con.execute("UPDATE mapas SET solo_propios=? WHERE id=?", (1 if valor else 0, mapa_id))


def grupo(codigo):
    with conectar() as con:
        r = con.execute("SELECT * FROM grupos WHERE codigo=?", (codigo.upper().strip(),)).fetchone()
        return dict(r) if r else None


def renombrar_grupo(codigo, nombre, nivel=None):
    with conectar() as con:
        con.execute("UPDATE grupos SET nombre=? WHERE codigo=?", (nombre.strip(), codigo))
        if nivel in (1, 2, 3):
            con.execute("UPDATE grupos SET nivel=? WHERE codigo=?", (int(nivel), codigo))


# ---------- Alumno ↔ grupo ----------
def registrar_alumno_en_grupo(seudonimo, equipo, codigo):
    """Entra un alumno. Si el seudónimo ya existe, solo puede volver a entrar en su mismo grupo y equipo
    (así nadie traslada el historial de otro a otro grupo). Devuelve un token de sesión."""
    g = grupo(codigo)
    if not g:
        raise ValueError("Ese código de grupo no existe")
    previo = obtener_alumno(seudonimo)
    if previo and previo.get("grupo") and previo["grupo"] != g["codigo"]:
        raise ValueError("Ese seudónimo ya está en otro grupo. Elige otro seudónimo")
    if previo and previo["equipo"] != equipo.lower():
        raise ValueError(f"Ese seudónimo ya es del equipo {previo['equipo']}. Entra con ese equipo o elige otro seudónimo")
    a = registrar_alumno(seudonimo, equipo)
    with conectar() as con:
        con.execute("UPDATE alumnos SET grupo=? WHERE seudonimo=?", (g["codigo"], seudonimo))
        token = secrets.token_urlsafe(24)
        con.execute("INSERT INTO sesiones_alumno VALUES (?,?,?)", (token, seudonimo, ahora()))
    a["token"] = token
    a["grupo"] = g["codigo"]
    a["grupo_nombre"] = g["nombre"]
    a["nivel"] = g.get("nivel") or 2
    a["mapas"] = [{"id": m["id"], "nombre": m["nombre"], "docente": m["docente_nombre"] or m["docente"]} for m in mapas_de_grupo(g["codigo"])]
    return a


def alumno_por_token(token):
    if not token:
        return None
    with conectar() as con:
        r = con.execute("SELECT seudonimo FROM sesiones_alumno WHERE token=?", (token,)).fetchone()
        return r["seudonimo"] if r else None


def grupo_de_alumno(seudonimo):
    with conectar() as con:
        r = con.execute("SELECT grupo FROM alumnos WHERE seudonimo=?", (seudonimo,)).fetchone()
        return r["grupo"] if r else None


def nivel_de_alumno(seudonimo):
    """Nivel cognitivo del grupo del alumno (1, 2 o 3). None si no tiene grupo."""
    cod = grupo_de_alumno(seudonimo)
    g = grupo(cod) if cod else None
    return (g.get("nivel") or 2) if g else None


# ---------- Tarea propuesta para un mapa (Critia 2.0) ----------
def guardar_tarea(mapa_id, tipo, tema, alcances, consigna, pasos, aprobada=False, entrega=None):
    with conectar() as con:
        con.execute("INSERT OR REPLACE INTO tareas (mapa_id, tipo, tema, alcances, consigna, pasos, aprobada, creado, entrega) VALUES (?,?,?,?,?,?,?,?,?)",
                    (int(mapa_id), tipo, tema, alcances or "", consigna, json.dumps(pasos, ensure_ascii=False), 1 if aprobada else 0, ahora(), entrega or None))
    return tarea_de_mapa(mapa_id)


# ---------- Avances de la tarea: lo que el alumno entrega en cada paso ----------
PUNTOS_AVANCE = 3          # puntos que da al territorio un avance aceptado por el docente
PARTICIPACION_MINIMA = 0.5 # parte del equipo que debe haber hecho el paso para poder ser dueño del territorio


def guardar_avance(seudonimo, mapa_id, mision, texto):
    """El alumno entrega (o vuelve a entregar) su avance de un paso. Un avance ya aceptado no se cambia."""
    with conectar() as con:
        r = con.execute("SELECT estado FROM avances WHERE seudonimo=? AND mapa_id=? AND mision=?", (seudonimo, mapa_id, mision)).fetchone()
        if r and r["estado"] == "aceptado":
            raise ValueError("Ese avance ya fue aceptado")
        con.execute("INSERT OR REPLACE INTO avances (seudonimo, mapa_id, mision, texto, enviado, estado) VALUES (?,?,?,?,?,'pendiente')",
                    (seudonimo, int(mapa_id), int(mision), texto, ahora()))


def avances_de_alumno(seudonimo, mapa_id):
    with conectar() as con:
        return {r["mision"]: {"texto": r["texto"], "estado": r["estado"], "nota": r["nota"] or "", "enviado": r["enviado"]}
                for r in con.execute("SELECT * FROM avances WHERE seudonimo=? AND mapa_id=?", (seudonimo, mapa_id))}


def avances_pendientes(codigos):
    f, params = _filtro_grupos(codigos)
    with conectar() as con:
        return [dict(r) for r in con.execute(f"""SELECT v.seudonimo, v.mapa_id, v.mision, v.texto, v.enviado, a.grupo, a.equipo, m.nombre mapa
                    FROM avances v JOIN alumnos a ON a.seudonimo=v.seudonimo JOIN mapas m ON m.id=v.mapa_id
                    WHERE v.estado='pendiente'{f} ORDER BY v.enviado""", params)]


def revisar_avance(seudonimo, mapa_id, mision, aceptar, nota, docente):
    with conectar() as con:
        cur = con.execute("UPDATE avances SET estado=?, nota=?, docente=?, revisado=? WHERE seudonimo=? AND mapa_id=? AND mision=?",
                          ("aceptado" if aceptar else "devuelto", (nota or "").strip()[:500], docente, ahora(), seudonimo, mapa_id, mision))
        return cur.rowcount > 0


def puntos_avances(seudonimo, mapa_id=None):
    """Puntos por avances aceptados del alumno (en un mapa o en todos)."""
    with conectar() as con:
        q, p = "SELECT COUNT(*) FROM avances WHERE seudonimo=? AND estado='aceptado'", [seudonimo]
        if mapa_id:
            q += " AND mapa_id=?"; p.append(mapa_id)
        return con.execute(q, p).fetchone()[0] * PUNTOS_AVANCE


def tarea_de_mapa(mapa_id):
    with conectar() as con:
        r = con.execute("SELECT * FROM tareas WHERE mapa_id=?", (mapa_id,)).fetchone()
        if not r:
            return None
        t = dict(r)
        t["pasos"] = json.loads(t["pasos"] or "[]")
        t["aprobada"] = bool(t["aprobada"])
        return t


# ---------- Casos ↔ mapa ----------
def asignar_caso(caso_id, mapa_ids):
    with conectar() as con:
        con.execute("DELETE FROM casos_mapa WHERE caso_id=?", (caso_id,))
        con.executemany("INSERT OR IGNORE INTO casos_mapa VALUES (?,?)", [(caso_id, int(m)) for m in mapa_ids])


def casos_del_mapa(mapa_id):
    with conectar() as con:
        return {r["caso_id"] for r in con.execute("SELECT caso_id FROM casos_mapa WHERE mapa_id=?", (mapa_id,))}


def mapas_del_caso(caso_id):
    with conectar() as con:
        return [r["mapa_id"] for r in con.execute("SELECT mapa_id FROM casos_mapa WHERE caso_id=?", (caso_id,))]


# ---------- Universo: territorios por mapa ----------
RACHA_BONO = 3        # racha personal (casos seguidos bien revisados) desde la que el alumno aporta bono a su equipo
PUNTOS_BONO = 2       # puntos que aporta esa racha en la misión donde el alumno está jugando
DETECTIVE_OK = 3      # criterios cumplidos (de 4) para que la reflexión del detective cuente para la isla


def universo(codigo, mision_de_caso, detective_ids=()):
    """Para cada mapa del grupo: sentidos por equipo en cada misión (territorio), insignias por equipo,
    bono de rachas personales e isla del detective. mision_de_caso: {caso_id: mision}."""
    g = grupo(codigo)
    if not g:
        return None
    detective_ids = set(detective_ids)
    with conectar() as con:
        alumnos_eq = {e: 0 for e in EQUIPOS}
        for r in con.execute("SELECT equipo, COUNT(*) n FROM alumnos WHERE grupo=? GROUP BY equipo", (g["codigo"],)):
            alumnos_eq[r["equipo"]] = r["n"]
        mapas = mapas_de_grupo(g["codigo"])
        salida = []
        totales = {e: {"territorios": 0, "insignias": 0, "sentidos": 0, "materias": 0, "rachas": 0, "islas": 0} for e in EQUIPOS}
        for m in mapas:
            terr = {}
            rachas = {}   # seudonimo -> [equipo, racha_actual, ultima_mision]
            for r in con.execute(f"""SELECT a.equipo, a.seudonimo, i.caso_id, i.sentidos, i.eval_ini, i.eval_fin, {SQL_PUNTOS} FROM intentos i JOIN alumnos a ON a.seudonimo=i.seudonimo
                                    WHERE i.cierre IS NOT NULL AND COALESCE(i.repeticion,0)=0 AND a.grupo=? AND i.mapa_id=? ORDER BY i.cierre""", (g["codigo"], m["id"])):
                mis = mision_de_caso.get(r["caso_id"])
                if not mis:
                    continue
                sent = json.loads(r["sentidos"] or "[]")
                n = puntos_territorio(sent, r["eval_fin"], r["pistas"], r["arm"])
                terr.setdefault(mis, {e: 0 for e in EQUIPOS})[r["equipo"]] += n
                totales[r["equipo"]]["sentidos"] += n
                st = rachas.setdefault(r["seudonimo"], [r["equipo"], 0, mis])
                ef = efecto_racha(sent, r["eval_ini"], r["armadura"])
                st[1] = st[1] + 1 if ef > 0 else (st[1] if ef == 0 else 0)
                st[2] = mis
            # bono de racha: cada alumno con racha >= RACHA_BONO empuja la misión donde está
            bonos = {}
            for eq, racha, mis in rachas.values():
                if racha >= RACHA_BONO:
                    terr.setdefault(mis, {e: 0 for e in EQUIPOS})[eq] += PUNTOS_BONO
                    bonos[eq] = bonos.get(eq, 0) + 1
                    totales[eq]["rachas"] += 1
            # Critia 2.0: avances de la tarea. Los aceptados dan puntos; los entregados cuentan como participación.
            tarea = tarea_de_mapa(m["id"])
            con_tarea = bool(tarea and tarea["aprobada"])
            hicieron = {}    # mision -> equipo -> alumnos que hicieron el paso
            if con_tarea:
                for r in con.execute("""SELECT a.equipo, a.seudonimo, v.mision, v.estado FROM avances v JOIN alumnos a ON a.seudonimo=v.seudonimo
                                        WHERE a.grupo=? AND v.mapa_id=?""", (g["codigo"], m["id"])):
                    if r["estado"] == "aceptado":
                        terr.setdefault(r["mision"], {e: 0 for e in EQUIPOS})[r["equipo"]] += PUNTOS_AVANCE
                        totales[r["equipo"]]["sentidos"] += PUNTOS_AVANCE
                    if r["estado"] in ("aceptado", "pendiente"):
                        hicieron.setdefault(r["mision"], {}).setdefault(r["equipo"], set()).add(r["seudonimo"])
            else:
                for r in con.execute("""SELECT a.equipo, a.seudonimo, i.caso_id FROM intentos i JOIN alumnos a ON a.seudonimo=i.seudonimo
                                        WHERE i.cierre IS NOT NULL AND a.grupo=? AND i.mapa_id=?""", (g["codigo"], m["id"])):
                    mis = mision_de_caso.get(r["caso_id"])
                    if mis:
                        hicieron.setdefault(mis, {}).setdefault(r["equipo"], set()).add(r["seudonimo"])
            ins = {e: 0 for e in EQUIPOS}
            ins_det = []  # [(equipo, postulado)] para las banderas
            for r in con.execute("""SELECT a.equipo, i.postulado FROM insignias i JOIN alumnos a ON a.seudonimo=i.seudonimo
                                    WHERE a.grupo=? AND i.mapa_id=?""", (g["codigo"], m["id"])):
                ins[r["equipo"]] += 1
                ins_det.append([r["equipo"], r["postulado"]])
            territorios = []
            for mis in range(1, 9):
                pts = terr.get(mis, {e: 0 for e in EQUIPOS})
                # Se compara el promedio por jugador, y solo puede ser dueño un equipo con participación suficiente
                prom = {e: (round(pts[e] / alumnos_eq[e], 2) if alumnos_eq[e] else 0) for e in EQUIPOS}
                part = {}
                for e in EQUIPOS:
                    n = len(hicieron.get(mis, {}).get(e, ()))
                    part[e] = {"hicieron": n, "jugadores": alumnos_eq[e],
                               "cumple": bool(alumnos_eq[e]) and n >= alumnos_eq[e] * PARTICIPACION_MINIMA}
                aptos = {e: prom[e] for e in EQUIPOS if part[e]["cumple"] and prom[e] > 0}
                top = max(aptos.values()) if aptos else 0
                lideres = [e for e, v in aptos.items() if v == top]
                dueno = lideres[0] if len(lideres) == 1 else None
                if dueno:
                    totales[dueno]["territorios"] += 1
                # el que va arriba en promedio pero todavía no tiene a la mitad de su equipo en el paso
                mejor = max(prom.values())
                falta = [e for e in EQUIPOS if mejor > 0 and prom[e] == mejor and not part[e]["cumple"]]
                territorios.append({"mision": mis, "dueno": dueno, "disputa": len(lideres) > 1, "puntos": pts,
                                    "promedio": prom, "participacion": part, "falta_participacion": falta})
            # isla del detective: equipo con más reflexiones del caso del detective aprobadas por el docente
            isla = {e: 0 for e in EQUIPOS}
            if detective_ids:
                q = ",".join("?" * len(detective_ids))
                for r in con.execute(f"""SELECT a.equipo, COUNT(*) n FROM intentos i JOIN alumnos a ON a.seudonimo=i.seudonimo
                                         JOIN revision_docente rd ON rd.intento_id=i.id
                                         WHERE a.grupo=? AND i.mapa_id=? AND i.caso_id IN ({q}) AND rd.puntaje>=? GROUP BY a.equipo""",
                                     (g["codigo"], m["id"], *detective_ids, DETECTIVE_OK)):
                    isla[r["equipo"]] = r["n"]
            top = max(isla.values())
            lid = [e for e, v in isla.items() if v == top and v > 0]
            isla_dueno = lid[0] if len(lid) == 1 else None
            if isla_dueno:
                totales[isla_dueno]["territorios"] += 1
                totales[isla_dueno]["islas"] += 1
            top = max(ins.values())
            lid = [e for e, v in ins.items() if v == top and v > 0]
            dueno_materia = lid[0] if len(lid) == 1 else None
            if dueno_materia:
                totales[dueno_materia]["materias"] += 1
            for e in EQUIPOS:
                totales[e]["insignias"] += ins[e]
            # Cierre del mapa: en la fecha de entrega gana el equipo con más territorios
            cierre = None
            if con_tarea:
                cuenta = {e: sum(1 for t in territorios if t["dueno"] == e) for e in EQUIPOS}
                mas = max(cuenta.values())
                punteros = [e for e, v in cuenta.items() if v == mas and v > 0]
                pasos = {p["mision"] for p in tarea["pasos"]}
                listos = {}
                for r in con.execute("""SELECT a.equipo, v.seudonimo, COUNT(*) n FROM avances v JOIN alumnos a ON a.seudonimo=v.seudonimo
                                        WHERE a.grupo=? AND v.mapa_id=? AND v.estado='aceptado' GROUP BY v.seudonimo""", (g["codigo"], m["id"])):
                    if r["n"] >= len(pasos):
                        listos[r["equipo"]] = listos.get(r["equipo"], 0) + 1
                cerrado = bool(tarea.get("entrega")) and ahora()[:10] > tarea["entrega"]
                cierre = {"entrega": tarea.get("entrega"), "cerrado": cerrado,
                          "puntero": punteros[0] if len(punteros) == 1 else None,
                          "ganador": (punteros[0] if len(punteros) == 1 else None) if cerrado else None,
                          "terminaron": {e: listos.get(e, 0) for e in EQUIPOS},
                          "equipo_completo": [e for e in EQUIPOS if alumnos_eq[e] and listos.get(e, 0) >= alumnos_eq[e]]}
            salida.append({"id": m["id"], "nombre": m["nombre"], "docente": m["docente_nombre"] or m["docente"],
                           "con_tarea": con_tarea, "cierre": cierre,
                           "territorios": territorios, "insignias": ins, "banderas": ins_det, "dueno": dueno_materia,
                           "rachas": bonos, "isla": {"dueno": isla_dueno, "disputa": len(lid) > 1, "puntos": isla}})
        return {"grupo": {"codigo": g["codigo"], "nombre": g["nombre"], "nivel": g.get("nivel") or 2},
                "alumnos": alumnos_eq, "mapas": salida, "totales": totales,
                "reglas": {"racha_bono": RACHA_BONO, "puntos_bono": PUNTOS_BONO, "detective_ok": DETECTIVE_OK,
                           "puntos_avance": PUNTOS_AVANCE, "participacion_minima": PARTICIPACION_MINIMA}}


def reto_semanal(codigo):
    """Reto de equipo de la semana en curso (lunes a domingo): casos bien revisados entre todos.
    La meta crece con el tamaño del equipo. No da puntos: es un logro compartido."""
    from datetime import date, timedelta
    hoy = date.fromisoformat(ahora()[:10])
    lunes = (hoy - timedelta(days=hoy.weekday())).isoformat()
    with conectar() as con:
        jugadores = {e: 0 for e in EQUIPOS}
        for r in con.execute("SELECT equipo, COUNT(*) n FROM alumnos WHERE grupo=? GROUP BY equipo", (codigo,)):
            jugadores[r["equipo"]] = r["n"]
        hechos = {e: 0 for e in EQUIPOS}
        for r in con.execute("""SELECT a.equipo, i.sentidos, i.eval_ini, i.armadura FROM intentos i JOIN alumnos a ON a.seudonimo=i.seudonimo
                                WHERE a.grupo=? AND i.cierre IS NOT NULL AND COALESCE(i.repeticion,0)=0 AND i.cierre>=?""", (codigo, lunes)):
            if efecto_racha(json.loads(r["sentidos"] or "[]"), r["eval_ini"], r["armadura"]) > 0:
                hechos[r["equipo"]] += 1
        out = {}
        for e in EQUIPOS:
            meta = max(RETO_MINIMO, RETO_POR_JUGADOR * jugadores[e]) if jugadores[e] else 0
            out[e] = {"hechos": hechos[e], "meta": meta, "cumplido": bool(meta and hechos[e] >= meta)}
        return {"desde": lunes, "equipos": out}


# ---------- Vistas filtradas por grupo ----------
def _filtro_grupos(codigos):
    if codigos is None:
        return "", ()
    if not codigos:
        return " AND 1=0", ()
    return f" AND a.grupo IN ({','.join('?'*len(codigos))})", tuple(codigos)


def tablero_equipos_grupo(codigo, mapa_id=None):
    fm = " AND i.mapa_id=?" if mapa_id else ""
    pm = (mapa_id,) if mapa_id else ()
    with conectar() as con:
        tab = {e: {"puntos": 0, "sentidos": 0, "casos": 0, "alumnos": 0, "insignias": 0, "justificar": 0, "revisar": 0, "calibrar": 0, "sin_ayuda": 0} for e in EQUIPOS}
        for r in con.execute("SELECT equipo, COUNT(*) n FROM alumnos WHERE grupo=? GROUP BY equipo", (codigo,)):
            tab[r["equipo"]]["alumnos"] = r["n"]
        for r in con.execute(f"""SELECT a.equipo, i.sentidos, i.eval_fin, {SQL_PUNTOS} FROM intentos i JOIN alumnos a ON a.seudonimo=i.seudonimo
                                WHERE i.cierre IS NOT NULL AND COALESCE(i.repeticion,0)=0 AND a.grupo=?{fm}""", (codigo,) + pm):
            s = json.loads(r["sentidos"] or "[]"); t = tab[r["equipo"]]
            t["sentidos"] += len(s); t["casos"] += 1
            t["puntos"] += puntos_territorio(s, r["eval_fin"], r["pistas"], r["arm"])
            t["sin_ayuda"] += 1 if (r["eval_fin"] == "correcta" and r["pistas"] <= 0) else 0
            for k in s:
                if k in t: t[k] += 1
        for r in con.execute(f"""SELECT a.equipo, COUNT(*) n FROM insignias i JOIN alumnos a ON a.seudonimo=i.seudonimo
                                WHERE a.grupo=?{fm} GROUP BY a.equipo""", (codigo,) + pm):
            tab[r["equipo"]]["insignias"] = r["n"]
        for e in EQUIPOS:
            tab[e]["avances"] = 0
        for r in con.execute(f"""SELECT a.equipo, COUNT(*) n FROM avances i JOIN alumnos a ON a.seudonimo=i.seudonimo
                                WHERE a.grupo=? AND i.estado='aceptado'{fm} GROUP BY a.equipo""", (codigo,) + pm):
            tab[r["equipo"]]["avances"] = r["n"]
            tab[r["equipo"]]["puntos"] += r["n"] * PUNTOS_AVANCE
        for e in EQUIPOS:
            tab[e]["promedio"] = round(tab[e]["puntos"] / tab[e]["alumnos"], 1) if tab[e]["alumnos"] else 0
        return tab


def resumen_grupo_codigos(codigos):
    f, params = _filtro_grupos(codigos)
    with conectar() as con:
        por_caso = [dict(r) for r in con.execute(f"""
            SELECT i.caso_id, COUNT(*) n, SUM(i.eval_ini='correcta') ok_ini,
                   SUM(i.eval_ini<>'correcta' AND i.eval_fin='correcta') mejoraron,
                   SUM(i.eval_ini<>'correcta' AND i.eval_fin<>'correcta') siguen_mal,
                   SUM(i.eval_fin='correcta' AND COALESCE(i.pistas_usadas,0)-COALESCE(i.reviso_antes,0)<=0) solos,
                   SUM(i.eval_fin='correcta' AND COALESCE(i.pistas_usadas,0)=1 AND COALESCE(i.reviso_antes,0)=0) con_pregunta,
                   SUM(COALESCE(i.reviso_antes,0)) revisaron, SUM(i.armadura='abollada') abolladas,
                   SUM(i.eval_fin='correcta' AND COALESCE(i.pistas_usadas,0)>=2) con_senalamiento,
                   SUM(COALESCE(i.pista_pedida,0)) pidieron,
                   ROUND(AVG(i.conf_ini)) conf_ini_prom, ROUND(AVG(i.conf_fin)) conf_fin_prom, SUM(i.reporta_duda) dudas
            FROM intentos i JOIN alumnos a ON a.seudonimo=i.seudonimo WHERE i.cierre IS NOT NULL{f} GROUP BY i.caso_id ORDER BY i.caso_id""", params)]
        por_familia = [dict(r) for r in con.execute(f"""
            SELECT i.tipo_error_ini familia, COUNT(*) n FROM intentos i JOIN alumnos a ON a.seudonimo=i.seudonimo
            WHERE i.cierre IS NOT NULL AND i.tipo_error_ini IS NOT NULL{f} GROUP BY i.tipo_error_ini ORDER BY n DESC""", params)]
        totales = dict(con.execute(f"""
            SELECT COUNT(DISTINCT i.seudonimo) alumnos, COUNT(*) intentos,
                   SUM(i.eval_ini<>'correcta' AND i.eval_fin='correcta') mejoraron, SUM(i.eval_ini<>'correcta') errores_ini,
                   SUM(i.armadura IS NOT NULL) con_armadura, SUM(COALESCE(i.reviso_antes,0)) revisaron,
                   SUM(i.armadura IN ('resiste','abollada')) armadura_alta, SUM(i.armadura='abollada') abolladas
            FROM intentos i JOIN alumnos a ON a.seudonimo=i.seudonimo WHERE i.cierre IS NOT NULL{f}""", params).fetchone())
        return {"totales": totales, "por_caso": por_caso, "por_familia": por_familia}


def lista_alumnos_codigos(codigos):
    f, params = _filtro_grupos(codigos)
    with conectar() as con:
        rows = con.execute(f"""
            SELECT a.seudonimo, a.equipo, a.grupo, COUNT(i.id) casos,
                   COALESCE(SUM(LENGTH(i.sentidos) - LENGTH(REPLACE(i.sentidos, ',', '')) + (i.sentidos <> '[]')), 0) sentidos,
                   (SELECT COUNT(*) FROM insignias x WHERE x.seudonimo=a.seudonimo) insignias
            FROM alumnos a LEFT JOIN intentos i ON i.seudonimo=a.seudonimo AND i.cierre IS NOT NULL
            WHERE 1=1{f} GROUP BY a.seudonimo ORDER BY a.grupo, a.equipo, a.seudonimo""", params).fetchall()
        lista = [dict(r) for r in rows]
        # puntos con la regla que ve el alumno (sin contar repeticiones)
        puntos = {}
        reviso, abolladas = {}, {}
        for r in con.execute(f"""SELECT i.seudonimo, i.sentidos, i.eval_fin, COALESCE(i.reviso_antes,0) reviso, {SQL_PUNTOS} FROM intentos i
                                WHERE i.cierre IS NOT NULL AND COALESCE(i.repeticion,0)=0"""):
            s = r["seudonimo"]
            puntos[s] = puntos.get(s, 0) + puntos_territorio(json.loads(r["sentidos"] or "[]"), r["eval_fin"], r["pistas"], r["arm"])
            reviso[s] = reviso.get(s, 0) + r["reviso"]
            abolladas[s] = abolladas.get(s, 0) + (1 if r["armadura"] == "abollada" else 0)
        for a in lista:
            a["puntos"] = puntos.get(a["seudonimo"], 0)
            a["reviso_antes"] = reviso.get(a["seudonimo"], 0)
            a["abolladas"] = abolladas.get(a["seudonimo"], 0)
        return lista


def reflexiones_pendientes_codigos(codigos):
    f, params = _filtro_grupos(codigos)
    with conectar() as con:
        rows = con.execute(f"""SELECT i.id, i.seudonimo, i.caso_id, i.reflexion, i.cierre, a.grupo FROM intentos i
                              JOIN alumnos a ON a.seudonimo=i.seudonimo
                              LEFT JOIN revision_docente r ON r.intento_id=i.id
                              WHERE i.reflexion IS NOT NULL AND i.reflexion<>'' AND r.intento_id IS NULL{f}
                              ORDER BY i.cierre""", params).fetchall()
        return [dict(r) for r in rows]


def sugerencias_insignia_codigos(casos_por_postulado, codigos):
    f, params = _filtro_grupos(codigos)
    with conectar() as con:
        rows = con.execute(f"""SELECT i.seudonimo, i.caso_id, COALESCE(i.mapa_id, 0) mapa_id FROM intentos i JOIN alumnos a ON a.seudonimo=i.seudonimo
                              WHERE i.cierre IS NOT NULL AND COALESCE(i.repeticion,0)=0 AND i.eval_ini='correcta' AND COALESCE(i.pistas_usadas,0)-COALESCE(i.reviso_antes,0)<=0{f}""", params).fetchall()
        conteo = {}
        for r in rows:
            p = casos_por_postulado.get(r["caso_id"])
            if p is None: continue
            conteo.setdefault((r["seudonimo"], p, r["mapa_id"]), set()).add(r["caso_id"])
        ya = {(r["seudonimo"], r["postulado"], r["mapa_id"]) for r in con.execute("SELECT seudonimo, postulado, mapa_id FROM insignias")}
        nombres = {r["id"]: r["nombre"] for r in con.execute("SELECT id, nombre FROM mapas")}
        return [{"seudonimo": k[0], "postulado": k[1], "mapa_id": k[2], "mapa": nombres.get(k[2], ""), "casos": sorted(v)}
                for k, v in conteo.items() if len(v) >= CASOS_PARA_INSIGNIA and k not in ya]


# ---------- Transferencia: ¿aplicó la habilidad en la tarea real? ----------
def marcar_transferencia(seudonimo, mapa_id, aplico, nota, docente):
    with conectar() as con:
        con.execute("INSERT OR REPLACE INTO transferencias VALUES (?,?,?,?,?,?)",
                    (seudonimo, int(mapa_id), 1 if aplico else 0, (nota or "").strip()[:300], docente, ahora()))


def transferencias_de(seudonimos):
    """{seudonimo: {mapa_id: {aplico, nota}}}"""
    if not seudonimos:
        return {}
    with conectar() as con:
        q = ",".join("?" * len(seudonimos))
        out = {}
        for r in con.execute(f"SELECT * FROM transferencias WHERE seudonimo IN ({q})", tuple(seudonimos)):
            out.setdefault(r["seudonimo"], {})[r["mapa_id"]] = {"aplico": bool(r["aplico"]), "nota": r["nota"] or ""}
        return out


def resumen_transferencia(codigos):
    """Por mapa: cuántos alumnos entrenaron (al menos un caso cerrado), cuántos tienen insignia
    y cuántos aplicaron la habilidad en la tarea real según el docente."""
    f, params = _filtro_grupos(codigos)
    with conectar() as con:
        mapas = [dict(r) for r in con.execute(f"""SELECT m.id, m.nombre, m.codigo, g.nombre grupo_nombre FROM mapas m
                    JOIN grupos g ON g.codigo=m.codigo JOIN alumnos a ON a.grupo=m.codigo WHERE 1=1{f} GROUP BY m.id""", params)]
        for m in mapas:
            m["entrenaron"] = con.execute("""SELECT COUNT(DISTINCT i.seudonimo) FROM intentos i JOIN alumnos a ON a.seudonimo=i.seudonimo
                                              WHERE a.grupo=? AND i.mapa_id=? AND i.cierre IS NOT NULL""", (m["codigo"], m["id"])).fetchone()[0]
            m["con_insignia"] = con.execute("""SELECT COUNT(DISTINCT i.seudonimo) FROM insignias i JOIN alumnos a ON a.seudonimo=i.seudonimo
                                                WHERE a.grupo=? AND i.mapa_id=?""", (m["codigo"], m["id"])).fetchone()[0]
            m["aplicaron"] = con.execute("""SELECT COUNT(*) FROM transferencias t JOIN alumnos a ON a.seudonimo=t.seudonimo
                                             WHERE a.grupo=? AND t.mapa_id=? AND t.aplico=1""", (m["codigo"], m["id"])).fetchone()[0]
            m["revisados"] = con.execute("""SELECT COUNT(*) FROM transferencias t JOIN alumnos a ON a.seudonimo=t.seudonimo
                                             WHERE a.grupo=? AND t.mapa_id=?""", (m["codigo"], m["id"])).fetchone()[0]
        return mapas
