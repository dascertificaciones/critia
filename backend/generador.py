"""
generador.py — Critia
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

HABILIDADES = {h["clave"]: h for h in META.get("marco_teorico", {}).get("habilidades", [])}
NIVELES = {n["n"]: n for n in META.get("marco_teorico", {}).get("niveles", [])}

GUIA_NIVEL = {
    1: "NIVEL 1 (11 a 12 años): la IA responde en UNA o DOS oraciones con un dato concreto. El fallo se descubre con una cuenta o una comparación simple. Vocabulario cotidiano, frases cortas, sin tecnicismos.",
    2: "NIVEL 2 (13 a 14 años): la IA responde en DOS o TRES oraciones con una explicación o una cita. El fallo está en el razonamiento o en la fuente (una referencia inventada, una generalización, un supuesto no dicho), no en el dato aislado.",
    3: "NIVEL 3 (15 a 17 años): la IA responde en UN PÁRRAFO con cifras, referencias y recomendaciones, mezclando afirmaciones ciertas con otras inventadas o exageradas. El alumno debe verificar afirmación por afirmación. Admite matices (una fuente real que no dice lo que la IA afirma, un supuesto presentado como normal).",
}

PROMPT_SISTEMA = """Eres un diseñador de ejercicios de pensamiento crítico sobre el uso responsable de la inteligencia artificial, para estudiantes mexicanos de 11 a 17 años.
REGLA CENTRAL: el objeto de análisis es SIEMPRE una respuesta textual de una IA. La situación tiene tres partes, en este orden:
1) "Le pediste a una IA: ..." (lo que el alumno preguntó),
2) "La IA respondió:" seguido de la respuesta COMPLETA entre comillas, escrita como la escribiría un asistente real (segura, amable, fluida), con el fallo dentro,
3) una línea de contexto o la decisión que debe tomar el alumno.
NUNCA describas el error como algo que hizo un compañero, un amigo o un tercero ("un niño dijo..."); el fallo está en la respuesta de la IA o en cómo se usaría.
Escribes en español neutro, claro y breve. Todos los nombres, datos, empresas, apps y estudios que menciones son FICTICIOS y no deben coincidir con personas o marcas reales.
Nunca incluyes datos personales reales, direcciones, teléfonos ni estereotipos sobre grupos de personas (salvo que el ejercicio sea para detectarlos, y entonces el estereotipo aparece como algo a cuestionar).
REGLAS SOBRE FUENTES Y DATOS (obligatorias):
a) NO atribuyas afirmaciones, cifras ni conclusiones a organizaciones, estudios, leyes o libros REALES. Si el caso necesita una fuente, invéntala y rotúlala dentro de la situación con la frase "inventado para este ejemplo" (p. ej. "el estudio y la revista son inventados para este ejemplo").
b) Si el alumno debe comprobar un hecho del mundo, usa solo hechos estables y de respuesta única en cualquier libro de texto (p. ej. una araña tiene 8 patas, un adulto tiene 206 huesos). Evita datos que cambian con el criterio de medición, la fecha o la fuente (el río más largo, la montaña más alta, la población actual, un récord) o que estén en disputa.
c) No encontrar una fuente nunca prueba que no exista. Redacta "no la encuentras" o "no aparece", nunca "no existe" como hecho del narrador. Enseña que una cita que no se puede abrir no sirve para apoyar un dato, sin afirmar que sea falsa.
d) Si dudas de una cifra real, usa un cálculo con números inventados dentro del mismo caso.
Devuelves SOLO un JSON válido, sin comentarios ni texto alrededor."""


def _prompt_usuario(tema, nivel, postulado, formato, n, familia):
    p = POSTULADOS[postulado]
    h = HABILIDADES.get(p.get("habilidad"), {})
    ejemplo = {
        "titulo": "Título corto",
        "situacion": "Le pediste a una IA: \"...\"\n\nLa IA respondió:\n\"...respuesta completa con el fallo dentro...\"\n\n(contexto o decisión). Máximo 120 palabras.",
        "pregunta": "¿Qué deberías hacer / decidir?",
        "opciones": [
            {"clave": "A", "texto": "Opción incorrecta que comete el error de la familia indicada", "correcta": False, "tipo_error": familia},
            {"clave": "B", "texto": "Opción correcta: la acción crítica adecuada", "correcta": True, "tipo_error": None},
            {"clave": "C", "texto": "Opción incorrecta: rechaza todo sin revisar", "correcta": False, "tipo_error": "desconfia_de_todo"},
        ],
        "pista_suave": "Pregunta general que activa la habilidad, sin mencionar datos del caso. Máximo 25 palabras.",
        "pista_fuerte": "Señala exactamente dónde está el fallo de la respuesta de la IA, sin dar la respuesta ni resolver la cuenta. Máximo 30 palabras.",
        "explicacion": "Por qué la correcta es correcta y por qué las otras no. Si hay cálculo, muéstralo. Máximo 90 palabras.",
        "reflexion": "Pregunta abierta de cierre que el alumno responde con sus palabras.",
        "rubrica_reflexion": ["criterio observable 1", "criterio observable 2"],
    }
    return f"""Genera {n} casos distintos sobre el tema "{tema}".
{GUIA_NIVEL.get(nivel, GUIA_NIVEL[2])}
Postulado de pensamiento crítico a practicar: {p['n']}. {p['nombre']}.
Habilidad del marco teórico que debe quedar en evidencia: {h.get('nombre', '')} ({h.get('autor', '')}): {h.get('definicion', '')}
La opción correcta debe ser exactamente lo que haría alguien que ejerce esa habilidad frente a la respuesta de la IA.
Familia de error principal que debe aparecer en una opción incorrecta: "{familia}".
Formato: {formato} (tres opciones A, B, C; exactamente UNA correcta; la posición de la correcta debe variar entre casos).
Las opciones incorrectas deben ser plausibles, no absurdas.
Las dos pistas son una escalera de ayuda: la suave solo hace pensar; la fuerte apunta al lugar del fallo. Ninguna de las dos puede contener la respuesta correcta ni el resultado de la cuenta.
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
REFERENCIA = re.compile(r"\b(estudio|informe|libro|enciclopedia|revista|art[ií]culo cient|investigaci[oó]n de|seg[uú]n el|seg[uú]n la)\b", re.I)
GRUPOS = re.compile(r"\b(los|las)\s+(mujeres|hombres|ni[ñn]as|ni[ñn]os|ind[ií]genas|pobres|ricos|gordos|flacos|morenos|g[üu]eros)\b", re.I)


def validar(caso, familias):
    """Devuelve lista de problemas (vacía si pasa)."""
    errores = []
    # compatibilidad: si solo viene 'pista', se usa como fuerte; la suave sale de la habilidad del postulado
    if caso.get("pista") and not caso.get("pista_fuerte"):
        caso["pista_fuerte"] = caso["pista"]
    if caso.get("pista_fuerte") and not caso.get("pista"):
        caso["pista"] = caso["pista_fuerte"]
    if not caso.get("pista_suave"):
        h = HABILIDADES.get(POSTULADOS.get(caso.get("postulado"), {}).get("habilidad"), {})
        if h.get("pregunta_suave"):
            caso["pista_suave"] = h["pregunta_suave"]
    for k in ["titulo", "situacion", "pregunta", "opciones", "pista_suave", "pista_fuerte", "explicacion", "reflexion", "rubrica_reflexion"]:
        if not caso.get(k):
            errores.append(f"falta {k}")
    # ninguna pista puede contener el texto de la opción correcta
    corr = next((o.get("texto", "") for o in (caso.get("opciones") or []) if o.get("correcta")), "")
    if corr and len(corr) > 12:
        for k in ("pista_suave", "pista_fuerte"):
            if corr.lower()[:40] in str(caso.get(k, "")).lower():
                errores.append(f"{k} contiene la respuesta correcta")
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
    sit = str(caso.get("situacion", ""))
    # una búsqueda fallida no prueba que algo no exista (se enseña como evidencia insuficiente)
    if re.search(r"\bno existe(n)?\b", sit + " " + " ".join(o.get("texto", "") for o in ops), re.I):
        errores.append("afirma que una fuente 'no existe'; redáctalo como 'no la encuentras'")
    # toda referencia simulada debe estar rotulada como inventada
    if REFERENCIA.search(sit) and not re.search(r"inventad", sit, re.I):
        errores.append("menciona una fuente o estudio sin rotularlo como 'inventado para este ejemplo'")
    return errores


def segunda_opinion(caso, api_key=None):
    """Filtro de consistencia: otro llamado al MISMO modelo, sin ver la clave, debe elegir la misma opción.
    Detecta casos ambiguos; no verifica hechos."""
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


def generar(tema, nivel_cog, postulado, formato="tres_opciones", n=2, mision=None, docente="docente", api_key=None):
    """Genera, valida y guarda. Devuelve {aceptados: [...], rechazados: [{caso, motivos}]}.
    nivel_cog: 1, 2 o 3 (madurez cognitiva por edad, ver misiones.json → marco_teorico.niveles)."""
    nivel_cog = int(nivel_cog) if str(nivel_cog) in ("1", "2", "3") else 2
    casos_existentes, familias = motor.cargar_casos()
    familia, nivel = POSTULADO_CFG.get(postulado, ("acepta_sin_evidencia", 2))
    mision = mision or next((m["n"] for m in META["misiones"] if postulado in m["postulados"]), 1)

    contenido = _llamar([{"role": "system", "content": PROMPT_SISTEMA},
                         {"role": "user", "content": _prompt_usuario(tema, nivel_cog, postulado, formato, n, familia)}],
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
                motivos.append("filtro de consistencia: el modelo no llegó a la misma respuesta sin ver la clave")
            elif so is None:
                motivos.append("no se pudo correr el filtro de consistencia (se marca para lectura completa)")
        grupos = GRUPOS.search(c.get("situacion", "") + " ".join(o.get("texto", "") for o in c.get("opciones", [])))
        nivel_final = 3 if (grupos or postulado in (8, 10, 11)) else nivel
        if motivos and any("filtro de consistencia:" in m for m in motivos):
            rechazados.append({"caso": c, "motivos": motivos}); continue
        if motivos and not all("no se pudo obtener" in m for m in motivos):
            rechazados.append({"caso": c, "motivos": motivos}); continue
        c.update({
            "id": f"{prefijo}-{siguiente:03d}", "mision": mision, "postulado": postulado,
            "familia_error": familia, "formato": formato, "nivel_revision": max(nivel_final, 2 if motivos else nivel_final),
            "provisional": True, "tema": tema, "nivel": nivel_cog,
            "habilidad": POSTULADOS[postulado].get("habilidad"), "generado_por": MODEL,
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
                for k in ["titulo", "situacion", "pregunta", "opciones", "pista", "pista_suave", "pista_fuerte", "explicacion", "reflexion", "rubrica_reflexion", "mision", "nivel_revision"]:
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
