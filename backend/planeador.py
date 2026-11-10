"""
planeador.py — Critia 2.0
Propone la tarea del grupo a partir del tipo de producto, el tema y los alcances que indica el docente.
La tarea se reparte en ocho pasos, uno por territorio: cada paso trabaja la misma habilidad que la misión
de ese territorio, para que el caso del juego y el avance de la tarea vayan juntos.

La propuesta sale de plantillas escritas a mano (no llama a ningún modelo). El docente la revisa,
la edita si quiere y la aprueba antes de que la vean los alumnos.
"""

PRODUCTOS = {
    "investigacion": {"nombre": "Investigación", "producto": "un reporte de investigación"},
    "infografia": {"nombre": "Infografía", "producto": "una infografía"},
    "mapa_mental": {"nombre": "Mapa mental", "producto": "un mapa mental"},
}

# Un paso por misión (territorio). Cuando el texto cambia según el producto, se indica por tipo.
PASOS = {
    1: {"titulo": "Lo que creo saber",
        "instruccion": "Escribe tres ideas que ya tienes sobre «{tema}». Junto a cada una anota cómo lo sabes. Marca las que necesitan comprobarse.",
        "entregable": "Tres ideas, cada una con su «¿cómo lo sé?»."},
    2: {"titulo": "Fuentes que sí puedo abrir",
        "instruccion": "Busca dos fuentes sobre «{tema}» que puedas abrir y leer: tu libro de texto, el sitio de una institución o una enciclopedia. Si una IA te sugiere una fuente, compruébala antes de anotarla.",
        "entregable": "Dos fuentes, con su título y dónde las encontraste."},
    3: {"titulo": "Mi pregunta con contexto",
        "instruccion": {
            "investigacion": "Escribe la pregunta que va a responder tu investigación. Incluye el lugar, el tiempo y para quién es. Después pide ayuda a una IA con esa pregunta y guarda su respuesta.",
            "infografia": "Define qué va a explicar tu infografía y para quién. Pide a una IA una lista de datos sobre «{tema}», dándole ese contexto, y guarda su respuesta.",
            "mapa_mental": "Escribe la idea central de tu mapa mental y para qué clase es. Pide a una IA los subtemas principales de «{tema}», dándole ese contexto, y guarda su respuesta."},
        "entregable": "Tu pregunta o idea central con su contexto, y la respuesta de la IA guardada."},
    4: {"titulo": "La IA contra mis fuentes",
        "instruccion": "Compara la respuesta de la IA con tus dos fuentes. Marca qué coincide, qué no coincide y qué no pudiste comprobar. Quédate solo con lo comprobado.",
        "entregable": "Una lista en tres partes: coincide, no coincide, no pude comprobar."},
    5: {"titulo": "Lo que se dice de las personas",
        "instruccion": "Revisa tu material. ¿Hay frases que generalizan sobre personas o grupos? Cámbialas por datos concretos o quítalas.",
        "entregable": "Las frases que corregiste, o «no encontré ninguna» con tu razón."},
    6: {"titulo": "Cuidar los datos",
        "instruccion": "Revisa lo que escribiste y lo que le diste a la IA. Quita nombres completos, direcciones, teléfonos o fotos de personas.",
        "entregable": "Qué datos quitaste, o «no había datos personales»."},
    7: {"titulo": "Hacerlo con mis palabras",
        "instruccion": {
            "investigacion": "Redacta tu reporte con tus palabras, a partir de lo que comprobaste. Agrega una nota que diga para qué usaste la IA y qué revisaste.",
            "infografia": "Arma tu infografía: un título, de tres a cinco datos comprobados con su fuente y un esquema o imagen hecho por ti. Agrega una nota que diga para qué usaste la IA y qué revisaste.",
            "mapa_mental": "Dibuja tu mapa mental: la idea central, de tres a cinco ramas y ejemplos con tus palabras. Agrega una nota que diga para qué usaste la IA y qué revisaste."},
        "entregable": "Tu trabajo en borrador y la nota de uso de IA."},
    8: {"titulo": "Una persona revisa",
        "instruccion": "Pide a un compañero o a tu maestro que revise tu trabajo. Anota qué te dijo y qué cambiaste. La decisión final es tuya.",
        "entregable": "Tu trabajo final, con lo que cambiaste después de la revisión."},
}


def proponer(tipo, tema, alcances, misiones):
    """Devuelve {consigna, pasos} para ese producto y tema. misiones: lista de META['misiones']."""
    if tipo not in PRODUCTOS:
        raise ValueError("Tipo de producto no válido")
    tema = (tema or "").strip()
    if len(tema) < 3:
        raise ValueError("Escribe el tema de la tarea")
    alcances = (alcances or "").strip()
    p = PRODUCTOS[tipo]
    consigna = (f"Vas a elaborar {p['producto']} sobre «{tema}». "
                + (f"{alcances.rstrip('.')}. " if alcances else "")
                + "Trabajarás en ocho pasos, uno por territorio del mapa. En cada paso puedes usar una IA, "
                  "pero antes de avanzar debes revisar lo que te respondió. Al terminar el mapa tendrás tu trabajo "
                  "completo y una nota que explica cómo usaste la IA.")
    pasos = []
    for m in misiones:
        base = PASOS.get(m["n"])
        if not base:
            continue
        ins = base["instruccion"]
        ins = ins[tipo] if isinstance(ins, dict) else ins
        pasos.append({"mision": m["n"], "titulo": base["titulo"], "instruccion": ins.format(tema=tema), "entregable": base["entregable"]})
    return {"consigna": consigna, "pasos": pasos}


def limpiar_pasos(pasos, misiones):
    """Valida los pasos que edita el docente: uno por misión existente, con textos acotados."""
    validas = {m["n"] for m in misiones}
    out, vistas = [], set()
    for p in pasos or []:
        try:
            n = int(p.get("mision"))
        except (TypeError, ValueError, AttributeError):
            raise ValueError("Cada paso debe indicar su territorio")
        if n not in validas or n in vistas:
            raise ValueError("Hay un paso repetido o de un territorio que no existe")
        titulo, ins = str(p.get("titulo") or "").strip()[:80], str(p.get("instruccion") or "").strip()[:600]
        if not titulo or not ins:
            raise ValueError(f"El paso del territorio {n} necesita título e instrucción")
        vistas.add(n)
        out.append({"mision": n, "titulo": titulo, "instruccion": ins, "entregable": str(p.get("entregable") or "").strip()[:300]})
    if not out:
        raise ValueError("La tarea necesita al menos un paso")
    return sorted(out, key=lambda x: x["mision"])
