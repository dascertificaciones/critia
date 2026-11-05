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
def registrar_alumno(seudonimo, equipo):
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
    with conectar() as con:
        cur = con.execute(
            "INSERT INTO intentos (seudonimo, caso_id, familia_caso, inicio, mapa_id) VALUES (?,?,?,?,?)",
            (seudonimo, caso_id, familia_caso, ahora(), mapa_id))
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


def progreso_alumno(seudonimo, casos_por_postulado=None, mapa_id=None):
    """Progreso del alumno. Con mapa_id, solo los intentos e insignias de ese mapa."""
    fm = " AND mapa_id=?" if mapa_id else ""
    pm = (mapa_id,) if mapa_id else ()
    with conectar() as con:
        rows = con.execute(f"""SELECT caso_id, sentidos, eval_ini, eval_fin FROM intentos
                              WHERE seudonimo=? AND cierre IS NOT NULL{fm} ORDER BY cierre""",
                           (seudonimo,) + pm).fetchall()
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
        ins = [r["postulado"] for r in con.execute(f"SELECT postulado FROM insignias WHERE seudonimo=?{fm}", (seudonimo,) + pm)]
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


def docente_por_token(token):
    if not token:
        return None
    with conectar() as con:
        r = con.execute("""SELECT d.usuario, d.nombre FROM sesiones_docente s JOIN docentes d ON d.usuario=s.usuario
                           WHERE s.token=? AND d.activo=1""", (token,)).fetchone()
        return dict(r) if r else None


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
                    (SELECT COUNT(*) FROM casos_mapa c WHERE c.mapa_id=m.id) casos_propios
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
    g = grupo(codigo)
    if not g:
        raise ValueError("Ese código de grupo no existe")
    a = registrar_alumno(seudonimo, equipo)
    with conectar() as con:
        con.execute("UPDATE alumnos SET grupo=? WHERE seudonimo=?", (g["codigo"], seudonimo))
    a["grupo"] = g["codigo"]
    a["grupo_nombre"] = g["nombre"]
    a["nivel"] = g.get("nivel") or 2
    a["mapas"] = [{"id": m["id"], "nombre": m["nombre"], "docente": m["docente_nombre"] or m["docente"]} for m in mapas_de_grupo(g["codigo"])]
    return a


def grupo_de_alumno(seudonimo):
    with conectar() as con:
        r = con.execute("SELECT grupo FROM alumnos WHERE seudonimo=?", (seudonimo,)).fetchone()
        return r["grupo"] if r else None


def nivel_de_alumno(seudonimo):
    """Nivel cognitivo del grupo del alumno (1, 2 o 3). None si no tiene grupo."""
    cod = grupo_de_alumno(seudonimo)
    g = grupo(cod) if cod else None
    return (g.get("nivel") or 2) if g else None


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
            for r in con.execute("""SELECT a.equipo, a.seudonimo, i.caso_id, i.sentidos, i.eval_ini FROM intentos i JOIN alumnos a ON a.seudonimo=i.seudonimo
                                    WHERE i.cierre IS NOT NULL AND a.grupo=? AND i.mapa_id=? ORDER BY i.cierre""", (g["codigo"], m["id"])):
                mis = mision_de_caso.get(r["caso_id"])
                if not mis:
                    continue
                sent = json.loads(r["sentidos"] or "[]")
                n = len(sent)
                terr.setdefault(mis, {e: 0 for e in EQUIPOS})[r["equipo"]] += n
                totales[r["equipo"]]["sentidos"] += n
                st = rachas.setdefault(r["seudonimo"], [r["equipo"], 0, mis])
                st[1] = st[1] + 1 if _bien_revisado(sent, r["eval_ini"]) else 0
                st[2] = mis
            # bono de racha: cada alumno con racha >= RACHA_BONO empuja la misión donde está
            bonos = {}
            for eq, racha, mis in rachas.values():
                if racha >= RACHA_BONO:
                    terr.setdefault(mis, {e: 0 for e in EQUIPOS})[eq] += PUNTOS_BONO
                    bonos[eq] = bonos.get(eq, 0) + 1
                    totales[eq]["rachas"] += 1
            ins = {e: 0 for e in EQUIPOS}
            ins_det = []  # [(equipo, postulado)] para las banderas
            for r in con.execute("""SELECT a.equipo, i.postulado FROM insignias i JOIN alumnos a ON a.seudonimo=i.seudonimo
                                    WHERE a.grupo=? AND i.mapa_id=?""", (g["codigo"], m["id"])):
                ins[r["equipo"]] += 1
                ins_det.append([r["equipo"], r["postulado"]])
            territorios = []
            for mis in range(1, 9):
                pts = terr.get(mis, {e: 0 for e in EQUIPOS})
                top = max(pts.values()) if pts else 0
                lideres = [e for e, v in pts.items() if v == top and v > 0]
                dueno = lideres[0] if len(lideres) == 1 else None
                if dueno:
                    totales[dueno]["territorios"] += 1
                territorios.append({"mision": mis, "dueno": dueno, "disputa": len(lideres) > 1, "puntos": pts})
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
            salida.append({"id": m["id"], "nombre": m["nombre"], "docente": m["docente_nombre"] or m["docente"],
                           "territorios": territorios, "insignias": ins, "banderas": ins_det, "dueno": dueno_materia,
                           "rachas": bonos, "isla": {"dueno": isla_dueno, "disputa": len(lid) > 1, "puntos": isla}})
        return {"grupo": {"codigo": g["codigo"], "nombre": g["nombre"], "nivel": g.get("nivel") or 2},
                "alumnos": alumnos_eq, "mapas": salida, "totales": totales,
                "reglas": {"racha_bono": RACHA_BONO, "puntos_bono": PUNTOS_BONO, "detective_ok": DETECTIVE_OK}}


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
        tab = {e: {"sentidos": 0, "casos": 0, "alumnos": 0, "insignias": 0, "justificar": 0, "revisar": 0, "calibrar": 0} for e in EQUIPOS}
        for r in con.execute("SELECT equipo, COUNT(*) n FROM alumnos WHERE grupo=? GROUP BY equipo", (codigo,)):
            tab[r["equipo"]]["alumnos"] = r["n"]
        for r in con.execute(f"""SELECT a.equipo, i.sentidos FROM intentos i JOIN alumnos a ON a.seudonimo=i.seudonimo
                                WHERE i.cierre IS NOT NULL AND a.grupo=?{fm}""", (codigo,) + pm):
            s = json.loads(r["sentidos"] or "[]"); t = tab[r["equipo"]]
            t["sentidos"] += len(s); t["casos"] += 1
            for k in s:
                if k in t: t[k] += 1
        for r in con.execute(f"""SELECT a.equipo, COUNT(*) n FROM insignias i JOIN alumnos a ON a.seudonimo=i.seudonimo
                                WHERE a.grupo=?{fm} GROUP BY a.equipo""", (codigo,) + pm):
            tab[r["equipo"]]["insignias"] = r["n"]
        return tab


def resumen_grupo_codigos(codigos):
    f, params = _filtro_grupos(codigos)
    with conectar() as con:
        por_caso = [dict(r) for r in con.execute(f"""
            SELECT i.caso_id, COUNT(*) n, SUM(i.eval_ini='correcta') ok_ini,
                   SUM(i.eval_ini<>'correcta' AND i.eval_fin='correcta') mejoraron,
                   SUM(i.eval_ini<>'correcta' AND i.eval_fin<>'correcta') siguen_mal,
                   ROUND(AVG(i.conf_ini)) conf_ini_prom, ROUND(AVG(i.conf_fin)) conf_fin_prom, SUM(i.reporta_duda) dudas
            FROM intentos i JOIN alumnos a ON a.seudonimo=i.seudonimo WHERE i.cierre IS NOT NULL{f} GROUP BY i.caso_id ORDER BY i.caso_id""", params)]
        por_familia = [dict(r) for r in con.execute(f"""
            SELECT i.tipo_error_ini familia, COUNT(*) n FROM intentos i JOIN alumnos a ON a.seudonimo=i.seudonimo
            WHERE i.cierre IS NOT NULL AND i.tipo_error_ini IS NOT NULL{f} GROUP BY i.tipo_error_ini ORDER BY n DESC""", params)]
        totales = dict(con.execute(f"""
            SELECT COUNT(DISTINCT i.seudonimo) alumnos, COUNT(*) intentos,
                   SUM(i.eval_ini<>'correcta' AND i.eval_fin='correcta') mejoraron, SUM(i.eval_ini<>'correcta') errores_ini
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
        return [dict(r) for r in rows]


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
                              WHERE i.cierre IS NOT NULL AND i.eval_ini='correcta'{f}""", params).fetchall()
        conteo = {}
        for r in rows:
            p = casos_por_postulado.get(r["caso_id"])
            if p is None: continue
            conteo.setdefault((r["seudonimo"], p, r["mapa_id"]), set()).add(r["caso_id"])
        ya = {(r["seudonimo"], r["postulado"], r["mapa_id"]) for r in con.execute("SELECT seudonimo, postulado, mapa_id FROM insignias")}
        nombres = {r["id"]: r["nombre"] for r in con.execute("SELECT id, nombre FROM mapas")}
        return [{"seudonimo": k[0], "postulado": k[1], "mapa_id": k[2], "mapa": nombres.get(k[2], ""), "casos": sorted(v)}
                for k, v in conteo.items() if len(v) >= CASOS_PARA_INSIGNIA and k not in ya]
