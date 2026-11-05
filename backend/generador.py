"""
generador.py — Sexto Sentido
Genera casos a partir de un tema usando un modelo (DeepSeek por defecto; API compatible con OpenAI),
los valida con filtros automáticos y los guarda como provisionales en casos/docente/.

Variables de entorno:
  LLM_API_KEY     clave del modelo (obligatoria para generar)
  LLM_BASE_URL    por defecto https://api.deepseek.com
  LLM_MODEL       por defecto deepseek-chat
"""
import json
import os
import re
import urllib.request
from datetime import datetime
from pathlib import Path

import motor

BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com").rstrip("/")
MODEL = os.environ.get("LLM_MODEL", "deepseek-chat")

META = json.loads((Path(__file__).parent / "misiones.json").read_text(encoding="utf-8"))
POSTULADOS = {p["n"]: p for p in META["postulados"]}

# Familia de error esperada y nivel de revisión según el postulado
POSTULADO_CFG = {
    1: ("acepta_sin_evidencia", 1), 2: ("acepta_sin_evidencia", 1), 3: ("confia_en_cita", 2),
    4: ("confunde_resultado_y_razonamiento", 1), 5: ("acepta_sin_evidencia", 1), 6: ("acepta_sin_evidencia", 1),
    7: ("ignora_contexto", 2), 8: ("generaliza", 3), 9: ("entrega_como_propio", 2),
    10: ("comparte_datos", 3), 11: ("no_consulta", 3), 12: ("entrega_como_propio", 2),
}

PROMPT_SISTEMA = """Eres un diseñador de ejercicios de pensamiento crítico para estudiantes mexicanos de secundaria (12 a 15 años).
Escribes en español neutro, claro y breve. Todos los nombres, datos, empresas, apps y estudios que menciones son FICTICIOS y no deben coincidir con personas o marcas reales.
Nunca incluyes datos personales reales, direcciones, teléfonos ni estereotipos sobre grupos de personas (salvo que el ejercicio sea para detectarlos, y entonces el estereotipo aparece como algo a cuestionar).
Devuelves SOLO un JSON válido, sin comentarios ni texto alrededor."""


def _prompt_usuario(tema, grado, postulado, formato, n, familia):
    p = POSTULADOS[postulado]
    ejemplo = {
        "titulo": "Título corto",
        "situacion": "Situación que lee el alumno. Si hay una respuesta de IA, inclúyela entre comillas. Máximo 90 palabras.",
        "pregunta": "¿Qué deberías hacer / decidir?",
        "opciones": [
            {"clave": "A", "texto": "Opción incorrecta que comete el error de la familia indicada", "correcta": False, "tipo_error": familia},
            {"clave": "B", "texto": "Opción correcta: la acción crítica adecuada", "correcta": True, "tipo_error": None},
            {"clave": "C", "texto": "Opción incorrecta: rechaza todo sin revisar", "correcta": False, "tipo_error": "desconfia_de_todo"},
        ],
        "pista": "Pregunta corta que hace dudar sin dar la respuesta.",
        "explicacion": "Por qué la correcta es correcta y por qué las otras no. Si hay cálculo, muéstralo. Máximo 90 palabras.",
        "reflexion": "Pregunta abierta de cierre que el alumno responde con sus palabras.",
        "rubrica_reflexion": ["criterio observable 1", "criterio observable 2"],
    }
    return f"""Genera {n} casos distintos sobre el tema "{tema}" para {grado}.
Postulado de pensamiento crítico a practicar: {p['n']}. {p['nombre']}.
Familia de error principal que debe aparecer en una opción incorrecta: "{familia}".
Formato: {formato} (tres opciones A, B, C; exactamente UNA correcta; la posición de la correcta debe variar entre casos).
Las opciones incorrectas deben ser plausibles, no absurdas.
Si el caso tiene números, las cuentas deben ser correctas y aparecer resueltas en la explicación.

Responde con un JSON con esta forma exacta: {{"casos": [ {json.dumps(ejemplo, ensure_ascii=False)} ]}}"""


def _llamar(messages, temperature=0.7, api_key=None):
    key = api_key or os.environ.get("LLM_API_KEY")
    if not key:
        raise RuntimeError("Falta LLM_API_KEY en el servidor")
    body = json.dumps({"model": MODEL, "messages": messages, "temperature": temperature,
                       "response_format": {"type": "json_object"}}).encode()
    req = urllib.request.Request(f"{BASE_URL}/chat/completions", data=body, headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.load(r)
    return data["choices"][0]["message"]["content"]


# ---------- Filtros ----------
PATRON_PERSONAL = re.compile(r"(\b\d{10}\b|@\w+\.\w{2,}|\bcalle\b.*\d+|\bcol\.|\bC\.P\.)", re.I)
GRUPOS = re.compile(r"\b(los|las)\s+(mujeres|hombres|ni[ñn]as|ni[ñn]os|ind[ií]genas|pobres|ricos|gordos|flacos|morenos|g[üu]eros)\b", re.I)


def validar(caso, familias):
    """Devuelve lista de problemas (vacía si pasa)."""
    errores = []
    for k in ["titulo", "situacion", "pregunta", "opciones", "pista", "explicacion", "reflexion", "rubrica_reflexion"]:
        if not caso.get(k):
            errores.append(f"falta {k}")
    ops = caso.get("opciones") or []
    if len(ops) < 3:
        errores.append("menos de 3 opciones")
    if sum(1 for o in ops if o.get("correcta")) != 1:
        errores.append("debe haber exactamente una opción correcta")
    claves = [o.get("clave") for o in ops]
    if claves != ["A", "B", "C"][:len(ops)]:
        errores.append("claves deben ser A, B, C en orden")
    for o in ops:
        if not o.get("correcta") and o.get("tipo_error") not in familias:
            errores.append(f"tipo_error inválido en {o.get('clave')}: {o.get('tipo_error')}")
    texto = " ".join(str(caso.get(k, "")) for k in ["situacion", "pregunta", "explicacion"]) + " ".join(o.get("texto", "") for o in ops)
    if PATRON_PERSONAL.search(texto):
        errores.append("posible dato personal (teléfono, correo, dirección)")
    if len(caso.get("situacion", "").split()) > 140:
        errores.append("situación demasiado larga")
    return errores


def segunda_opinion(caso, api_key=None):
    """Otro llamado sin ver la clave: debe elegir la misma opción correcta."""
    ops = "\n".join(f"{o['clave']}) {o['texto']}" for o in caso["opciones"])
    msg = [{"role": "system", "content": "Eres un experto en pensamiento crítico. Responde solo con la letra de la mejor opción."},
           {"role": "user", "content": f"{caso['situacion']}\n\n{caso['pregunta']}\n{ops}\n\nResponde en JSON: {{\"letra\": \"A\"}}"}]
    try:
        r = json.loads(_llamar(msg, temperature=0, api_key=api_key))
        elegida = str(r.get("letra", "")).strip().upper()[:1]
    except Exception:
        return None
    correcta = next(o["clave"] for o in caso["opciones"] if o["correcta"])
    return elegida == correcta


def generar(tema, grado, postulado, formato="tres_opciones", n=2, mision=None, docente="docente", api_key=None):
    """Genera, valida y guarda. Devuelve {aceptados: [...], rechazados: [{caso, motivos}]}."""
    casos_existentes, familias = motor.cargar_casos()
    familia, nivel = POSTULADO_CFG.get(postulado, ("acepta_sin_evidencia", 2))
    mision = mision or next((m["n"] for m in META["misiones"] if postulado in m["postulados"]), 1)

    contenido = _llamar([{"role": "system", "content": PROMPT_SISTEMA},
                         {"role": "user", "content": _prompt_usuario(tema, grado, postulado, formato, n, familia)}],
                        api_key=api_key)
    try:
        lote = json.loads(contenido).get("casos", [])
    except json.JSONDecodeError:
        raise RuntimeError("El modelo no devolvió JSON válido")

    aceptados, rechazados = [], []
    prefijo = "GEN-" + re.sub(r"[^A-Z0-9]", "", tema.upper())[:6]
    existentes = [c for c in casos_existentes if c.startswith(prefijo)]
    siguiente = len(existentes) + 1
    archivo = motor.CASOS_DIR / "docente" / f"casos_generados_{datetime.now():%Y%m%d}.json"
    datos = json.loads(archivo.read_text(encoding="utf-8")) if archivo.exists() else {"casos": []}

    for c in lote:
        motivos = validar(c, familias)
        if not motivos:
            so = segunda_opinion(c, api_key=api_key)
            if so is False:
                motivos.append("segunda opinión ciega no coincide con la clave")
            elif so is None:
                motivos.append("no se pudo obtener segunda opinión (se marca para lectura completa)")
        grupos = GRUPOS.search(c.get("situacion", "") + " ".join(o.get("texto", "") for o in c.get("opciones", [])))
        nivel_final = 3 if (grupos or postulado in (8, 10, 11)) else nivel
        if motivos and any("segunda opinión ciega" in m for m in motivos):
            rechazados.append({"caso": c, "motivos": motivos}); continue
        if motivos and not all("no se pudo obtener" in m for m in motivos):
            rechazados.append({"caso": c, "motivos": motivos}); continue
        c.update({
            "id": f"{prefijo}-{siguiente:03d}", "mision": mision, "postulado": postulado,
            "familia_error": familia, "formato": formato, "nivel_revision": max(nivel_final, 2 if motivos else nivel_final),
            "provisional": True, "tema": tema, "grado": grado, "generado_por": MODEL,
            "generado_el": datetime.now().isoformat(timespec="seconds"), "docente": docente,
        })
        siguiente += 1
        datos["casos"].append(c)
        aceptados.append(c)

    archivo.parent.mkdir(parents=True, exist_ok=True)
    archivo.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"aceptados": aceptados, "rechazados": rechazados, "archivo": archivo.name}


def actualizar_caso(caso_id, cambios, solo_de=None):
    """Edita campos de un caso en la carpeta docente/. solo_de: usuario dueño (None = cualquiera)."""
    for f in (motor.CASOS_DIR / "docente").glob("*.json"):
        datos = json.loads(f.read_text(encoding="utf-8"))
        for c in datos.get("casos", []):
            if c["id"] == caso_id and (solo_de is None or c.get("docente") == solo_de):
                for k in ["titulo", "situacion", "pregunta", "opciones", "pista", "explicacion", "reflexion", "rubrica_reflexion", "mision", "nivel_revision"]:
                    if k in cambios:
                        c[k] = cambios[k]
                f.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
                return c
    raise KeyError(caso_id)


def eliminar_caso(caso_id, solo_de=None):
    for f in (motor.CASOS_DIR / "docente").glob("*.json"):
        datos = json.loads(f.read_text(encoding="utf-8"))
        antes = len(datos.get("casos", []))
        datos["casos"] = [c for c in datos.get("casos", []) if not (c["id"] == caso_id and (solo_de is None or c.get("docente") == solo_de))]
        if len(datos["casos"]) != antes:
            f.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
            return True
    return False
