"""
historial.py — Sexto Sentido
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
EQUIPOS = ["rojo", "azul", "verde", "amarillo"]

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
def registrar_alumno(seudonimo, equipo):
    equipo = equipo.lower()
    if equipo not in EQUIPOS:
        raise ValueError(f"Equipo inválido: {equipo}")
    with conectar() as con:
        con.execute("INSERT OR IGNORE INTO alumnos VALUES (?,?,?)", (seudonimo, equipo, ahora()))
        return dict(con.execute("SELECT * FROM alumnos WHERE seudonimo=?", (seudonimo,)).fetchone())


def obtener_alumno(seudonimo):
    with conectar() as con:
        r = con.execute("SELECT * FROM alumnos WHERE seudonimo=?", (seudonimo,)).fetchone()
        return dict(r) if r else None


# ---------- Intentos ----------
def abrir_intento(seudonimo, caso_id, familia_caso):
    with conectar() as con:
        cur = con.execute(
            "INSERT INTO intentos (seudonimo, caso_id, familia_caso, inicio) VALUES (?,?,?,?)",
            (seudonimo, caso_id, familia_caso, ahora()))
        return cur.lastrowid


def intento_abierto(seudonimo, caso_id):
    """Intento sin cerrar para ese alumno y caso (permite retomar)."""
    with conectar() as con:
        r = con.execute(
            "SELECT * FROM intentos WHERE seudonimo=? AND caso_id=? AND cierre IS NULL ORDER BY id DESC LIMIT 1",
            (seudonimo, caso_id)).fetchone()
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
RACHA_PARA_DETECTIVE = 3   # casos seguidos "bien revisados" para desbloquear el caso del detective
CASOS_PARA_INSIGNIA = 2    # casos del mismo postulado sin pista para sugerir insignia


def _bien_revisado(sentidos, eval_ini):
    """Cuenta para la racha: acertó sin pista, o corrigió después de la pista."""
    return eval_ini == "correcta" or "revisar" in sentidos


def progreso_alumno(seudonimo, casos_por_postulado=None):
    with conectar() as con:
        rows = con.execute("""SELECT caso_id, sentidos, eval_ini, eval_fin FROM intentos
                              WHERE seudonimo=? AND cierre IS NOT NULL ORDER BY cierre""",
                           (seudonimo,)).fetchall()
        casos, total, racha, mejor_racha = {}, 0, 0, 0
        avance = {}
        for r in rows:
            s = json.loads(r["sentidos"] or "[]")
            casos[r["caso_id"]] = {"sentidos": s, "eval_ini": r["eval_ini"], "eval_fin": r["eval_fin"]}
            total += len(s)
            if _bien_revisado(s, r["eval_ini"]):
                racha += 1
                mejor_racha = max(mejor_racha, racha)
            else:
                racha = 0
            if casos_por_postulado and r["eval_ini"] == "correcta":
                p = casos_por_postulado.get(r["caso_id"])
                if p:
                    avance.setdefault(str(p), set()).add(r["caso_id"])
        ins = [r["postulado"] for r in con.execute("SELECT postulado FROM insignias WHERE seudonimo=?", (seudonimo,))]
        return {
            "casos": casos,
            "sentidos_total": total,
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
def otorgar_insignia(seudonimo, postulado, por="docente"):
    with conectar() as con:
        con.execute("INSERT OR REPLACE INTO insignias VALUES (?,?,?,?)", (seudonimo, postulado, ahora(), por))


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


def alerta_casos():
    """Casos donde más del 80% mantiene el error tras la pista, o nadie se equivoca."""
    with conectar() as con:
        rows = con.execute("""SELECT caso_id,
                                COUNT(*) n,
                                SUM(eval_ini<>'correcta') err_ini,
                                SUM(eval_ini<>'correcta' AND eval_fin<>'correcta') err_fin,
                                SUM(reporta_duda) dudas
                              FROM intentos WHERE cierre IS NOT NULL GROUP BY caso_id""").fetchall()
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
                              clave_fin, conf_fin, eval_fin, accion_fin, motivo_fin, sentidos, reflexion, reporta_duda
                              FROM intentos WHERE seudonimo=? AND cierre IS NOT NULL ORDER BY inicio""", (seudonimo,)).fetchall()
        out = []
        for r in rows:
            d = dict(r); d["sentidos"] = json.loads(d["sentidos"] or "[]"); out.append(d)
        return out
