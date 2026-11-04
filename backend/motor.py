"""
motor.py — Sexto Sentido
Carga el banco de casos, arma los hechos ASP, llama al solver
(clingo por defecto; DLV si está instalado) y devuelve la acción y el motivo.
"""
import json
import os
import shutil
import subprocess
from pathlib import Path

BASE = Path(__file__).parent
ASP_DIR = BASE / "asp"
CASOS_DIR = BASE / "casos"

# ---------- Textos que ve el alumno ----------
TEXTO_ACCION = {
    "advertir_privacidad": "Antes de seguir: ¿esta app o este mensaje necesitan de verdad lo que te piden? ¿Qué pasaría si lo compartes?",
    "comparar_con_anterior": "Ya te pasó algo parecido en un caso anterior. ¿Qué hiciste la vez pasada para darte cuenta?",
    "pedir_verificacion": "Vamos a comprobarlo paso a paso. ¿Qué dato tendrías que revisar para estar seguro?",
    "pedir_contraejemplo": "Rechazar todo sin revisar tampoco es pensar críticamente. ¿Hay algún caso en que la IA sí podría ayudar?",
    "pedir_contexto": "La respuesta no dice bajo qué condiciones aplica. ¿Qué falta en la pregunta?",
    "sugerir_calculo": "Revisa cada respuesta en dos partes: el razonamiento y la cuenta. ¿Las dos están bien?",
    "pedir_criterio_justo": "¿Ese consejo se basa en lo que cada persona sabe hacer, o en un grupo al que pertenece?",
    "remitir_a_persona": "¿Quién puede revisar esto de verdad y hacerse responsable? ¿Una IA puede hacerlo?",
    "preguntar_autoria": "¿Qué parte del trabajo es tuya? ¿Qué aprendiste al hacerlo?",
    "pedir_evidencia": "No estás muy seguro, y está bien. ¿Qué evidencia te ayudaría a decidir?",
    "reforzar_confianza": "Tu respuesta es correcta. ¿Por qué dudaste? Explica qué la hace correcta.",
    "confirmar": "Correcto. Explica con tus palabras por qué elegiste esa opción.",
    "cerrar_elogio_calibrado": "Buena revisión. Cambiaste a la respuesta correcta y ajustaste tu confianza.",
    "cerrar_elogio": "Buena revisión. Llegaste a la respuesta correcta.",
    "cerrar_mantuvo": "Mantuviste la respuesta correcta. Bien.",
    "cerrar_explicar_cambio": "Cambiaste de respuesta, pero a otra que tampoco funciona. Lee la explicación con calma.",
    "cerrar_explicar": "Mantuviste tu respuesta. Lee la explicación y compárala con lo que pensaste.",
    "cerrar_revisar_duda": "Tu primera respuesta era la correcta. ¿Qué te hizo cambiarla?",
}

TEXTO_MOTIVO = {
    "riesgo_privacidad": "La opción elegida implica compartir datos o confiar en contenido sin confirmar.",
    "error_repetido": "Este tipo de error ya apareció en casos anteriores del historial.",
    "acepta_sin_evidencia_seguro": "Se aceptó una afirmación sin evidencia con confianza alta.",
    "desconfia_de_todo": "Se rechazó la herramienta sin revisar; eso tampoco es criterio.",
    "falta_contexto": "La respuesta omite las condiciones en que aplica.",
    "calculo_dudoso": "Se confundió un razonamiento correcto con un resultado correcto.",
    "generaliza": "Se aceptó una generalización sobre personas sin evidencia.",
    "no_consulta": "La situación requiere a una persona con criterio, no una respuesta automática.",
    "entrega_como_propio": "Se presentó trabajo de la IA como propio.",
    "error_inseguro": "Respuesta incorrecta con confianza baja: conviene buscar evidencia.",
    "error_seguro": "Respuesta incorrecta con confianza alta.",
    "correcta_insegura": "Respuesta correcta con confianza baja.",
    "correcta_segura": "Respuesta correcta con confianza adecuada.",
    "mejoro_y_calibro": "La revisión corrigió el error y la confianza se ajustó.",
    "mejoro": "La revisión corrigió el error inicial.",
    "mantuvo_correcta": "La respuesta correcta se mantuvo tras la pista.",
    "cambio_a_otro_error": "La revisión cambió la respuesta, pero a otra incorrecta.",
    "no_cambio": "La revisión no cambió la respuesta incorrecta.",
    "empeoro": "La revisión cambió una respuesta correcta por una incorrecta.",
    "fase_final": "Cierre del caso.",
}


# ---------- Banco de casos ----------
def cargar_casos():
    """Une casos.json con los archivos de la carpeta docente/."""
    base = json.loads((CASOS_DIR / "casos.json").read_text(encoding="utf-8"))
    casos = {c["id"]: c for c in base["casos"]}
    familias = set(base["familias_error"])
    for f in sorted((CASOS_DIR / "docente").glob("*.json")):
        extra = json.loads(f.read_text(encoding="utf-8"))
        for c in extra.get("casos", []):
            c.setdefault("provisional", True)
            c["origen"] = f.name
            casos[c["id"]] = c
    return casos, familias


def caso_para_alumno(caso):
    """Versión del caso sin la clave de respuesta."""
    return {
        "id": caso["id"],
        "mision": caso["mision"],
        "postulado": caso["postulado"],
        "formato": caso["formato"],
        "titulo": caso["titulo"],
        "situacion": caso["situacion"],
        "pregunta": caso["pregunta"],
        "opciones": [{"clave": o["clave"], "texto": o["texto"]} for o in caso["opciones"]],
        "provisional": caso.get("provisional", False),
        "especial": caso.get("especial"),
    }


def evaluar_opcion(caso, clave):
    """Devuelve (evaluacion, tipo_error) según la clave editorial."""
    if caso["formato"] == "reflexion_abierta":
        return "abierta", None
    for o in caso["opciones"]:
        if o["clave"] == clave:
            if o["correcta"]:
                return "correcta", None
            esperado = o["tipo_error"] == caso.get("familia_error")
            return ("error_esperado" if esperado else "error_otro"), o["tipo_error"]
    raise ValueError(f"Opción {clave} no existe en {caso['id']}")


# ---------- Hechos ASP ----------
def armar_hechos(caso, fase, inicial, final=None, ayuda_previa=False, historial_errores=None):
    """
    inicial / final: dict con clave, confianza, justificacion, evaluacion, tipo_error
    historial_errores: dict familia -> cantidad de errores iniciales previos
    """
    h = [f"fase({fase}).", f"familia_caso({caso.get('familia_error') or 'ninguna'})."]

    def fase_hechos(nombre, r):
        if r is None:
            return []
        out = [
            f"respuesta({nombre}, {r['clave'].lower()}, {r['evaluacion']}).",
            f"confianza({nombre}, {int(r['confianza'])}).",
        ]
        if r.get("tipo_error"):
            out.append(f"tipo_error({nombre}, {r['tipo_error']}).")
        if r.get("justificacion"):
            out.append(f"justifico({nombre}).")
        return out

    h += fase_hechos("inicial", inicial)
    h += fase_hechos("final", final)
    if ayuda_previa:
        h.append("ayuda_previa.")
    for fam, n in (historial_errores or {}).items():
        h.append(f"historial_error({fam}, {n}).")
    return "\n".join(h)


# ---------- Solver ----------
def _correr_clingo(programa):
    import clingo
    ctl = clingo.Control(["0", "--warn=none"])
    ctl.add("base", [], programa)
    ctl.ground([("base", [])])
    modelos = []
    ctl.solve(on_model=lambda m: modelos.append([str(s) for s in m.symbols(shown=True)]))
    return modelos


def _correr_dlv(programa):
    binario = shutil.which("dlv2") or shutil.which("dlv")
    limpio = "\n".join(l for l in programa.splitlines() if not l.strip().startswith("#show"))
    res = subprocess.run([binario, "--silent", "--"], input=limpio, capture_output=True, text=True)
    atomos = res.stdout.strip().strip("{}").split(", ")
    return [[a for a in atomos if a.startswith(("seleccionada", "diagnostico", "sentido"))]]


def consultar(hechos):
    """Devuelve dict con accion, motivo, diagnosticos, sentidos y textos."""
    reglas = (ASP_DIR / "diagnostico.dlv").read_text() + "\n" + (ASP_DIR / "tutor.dlv").read_text()
    programa = reglas + "\n" + hechos
    modelos = _correr_dlv(programa) if (shutil.which("dlv2") or shutil.which("dlv")) else _correr_clingo(programa)
    if len(modelos) != 1:
        raise RuntimeError(f"Se esperaba 1 modelo, hay {len(modelos)}")
    atomos = modelos[0]
    sel = [a for a in atomos if a.startswith("seleccionada(")]
    if len(sel) != 1:
        raise RuntimeError(f"Se esperaba 1 acción, hay {len(sel)}: {sel}")
    accion, motivo = sel[0][len("seleccionada("):-1].split(",")
    diag = sorted(a[len("diagnostico("):-1] for a in atomos if a.startswith("diagnostico("))
    sentidos = sorted(a[len("sentido("):-1] for a in atomos if a.startswith("sentido("))
    return {
        "accion": accion,
        "motivo": motivo,
        "texto_accion": TEXTO_ACCION.get(accion, accion),
        "texto_motivo": TEXTO_MOTIVO.get(motivo, motivo),
        "diagnosticos": diag,
        "sentidos": sentidos,
    }
