"""
sesion.py — Critia
Flujo de un caso: abrir → responder (fase inicial) → revisar (fase final) → reflexionar.
Lo usan tanto la consola (critia.py) como la API (main.py).
"""
import motor
import historial


def _validar_conf(c):
    c = int(c)
    if not 0 <= c <= 100:
        raise ValueError("La confianza va de 0 a 100")
    return c


def abrir(seudonimo, caso_id, mapa_id=None):
    casos, _ = motor.cargar_casos()
    caso = casos[caso_id]
    abierto = historial.intento_abierto(seudonimo, caso_id, mapa_id)
    intento_id = abierto["id"] if abierto else historial.abrir_intento(seudonimo, caso_id, caso.get("familia_error"), mapa_id)
    return {"intento_id": intento_id, "caso": motor.caso_para_alumno(caso),
            "retomado": bool(abierto and abierto.get("clave_ini")),
            "estado": _estado(caso, abierto) if abierto else None}


def _estado(caso, it):
    """Lo que el alumno ya hizo en un intento sin cerrar, para retomarlo donde se quedó.
    Solo incluye sus propias decisiones y las pistas que ya recibió."""
    pistas = it.get("pistas_usadas") or 0
    con_pistas = caso["formato"] != "reflexion_abierta"
    return {
        "clave_ini": it.get("clave_ini"), "conf_ini": it.get("conf_ini"), "just_ini": it.get("just_ini"),
        "clave_med": it.get("clave_med"), "conf_med": it.get("conf_med"),
        "pistas_usadas": pistas, "pista_pedida": bool(it.get("pista_pedida")),
        "reviso_antes": bool(it.get("reviso_antes")), "armadura": it.get("armadura"),
        "pista": _pista(caso, pistas) if (pistas and con_pistas) else None,
        "texto_accion": motor.TEXTO_ACCION.get(it.get("accion_ini")) if it.get("accion_ini") else None,
        "texto_motivo": motor.TEXTO_MOTIVO.get(it.get("motivo_ini")) if it.get("motivo_ini") else None,
    }


def _pista(caso, nivel):
    """Nivel 1: pregunta general (del caso o, si no tiene, la de su habilidad). Nivel 2: señalamiento del fallo."""
    if nivel >= 2:
        return caso.get("pista_fuerte") or caso.get("pista")
    if caso.get("pista_suave"):
        return caso["pista_suave"]
    h = motor.habilidad_de(caso)
    hd = next((x for x in motor.META["marco_teorico"]["habilidades"] if h and x["clave"] == h["clave"]), None)
    return (hd or {}).get("pregunta_suave") or caso.get("pista")


def pedir_pista(intento_id):
    """El alumno pide ayuda antes de decidir. Sube un escalón cada vez (máximo 2)."""
    it = historial.obtener_intento(intento_id)
    if not it:
        raise KeyError("intento inexistente")
    if it.get("clave_ini") or it.get("cierre"):
        raise ValueError("Las pistas se piden antes de decidir")
    casos, _ = motor.cargar_casos()
    caso = casos[it["caso_id"]]
    if caso["formato"] == "reflexion_abierta":
        raise ValueError("Este caso no tiene pistas")
    nivel = min(2, (it.get("pistas_usadas") or 0) + 1)
    historial.guardar_pista(intento_id, nivel, pedida=True)
    # La primera es «revisar primero»: una pregunta para comprobar la respuesta de la IA. No cuenta como ayuda.
    gratis = nivel == 1
    if gratis:
        historial.marcar_reviso(intento_id)
    accion, motivo = ("revision_previa", "revision_a_peticion") if gratis else ("pista_pedida", "pista_a_peticion")
    return {"accion": accion, "motivo": motivo, "texto_accion": motor.TEXTO_ACCION[accion],
            "texto_motivo": motor.TEXTO_MOTIVO[motivo], "pista": _pista(caso, nivel), "nivel": nivel,
            "quedan": 2 - nivel, "gratis": gratis}


def responder(intento_id, clave, confianza, justificacion=""):
    """Decisión 1. Devuelve la intervención del tutor (pista + motivo).
    Si hubo error, la pista es suave (pregunta) o fuerte (señalamiento) según las reglas ASP y las pistas ya pedidas."""
    it = historial.obtener_intento(intento_id)
    if not it:
        raise KeyError("intento inexistente")
    if it.get("clave_ini") or it.get("cierre"):
        raise ValueError("Este intento ya tiene una decisión inicial; no se puede reescribir")
    casos, _ = motor.cargar_casos()
    caso = casos[it["caso_id"]]
    conf = _validar_conf(confianza)

    if caso["formato"] == "reflexion_abierta":
        historial.guardar_inicial(intento_id, "-", conf, justificacion, "abierta", None, "pedir_reflexion", "formato_abierto")
        return {"accion": "pedir_reflexion", "motivo": "formato_abierto",
                "texto_accion": caso["pista"], "texto_motivo": "Caso de reflexión abierta; lo revisa el docente.",
                "pista": caso["pista"], "diagnosticos": []}

    eval_, tipo = motor.evaluar_opcion(caso, clave.upper())
    inicial = {"clave": clave, "confianza": conf, "justificacion": justificacion, "evaluacion": eval_, "tipo_error": tipo}
    mision_de = {c["id"]: c["mision"] for c in casos.values()}
    fmp = historial.fallo_mision_previa(it["seudonimo"], it.get("mapa_id"), mision_de, caso["mision"])
    hechos = motor.armar_hechos(caso, "inicial", inicial, historial_errores=historial.errores_previos(it["seudonimo"]), fallo_mision_previa=fmp)
    r = motor.consultar(hechos)
    historial.guardar_inicial(intento_id, clave.upper(), conf, justificacion, eval_, tipo, r["accion"], r["motivo"])
    # La armadura (seguridad inicial) se pone a prueba con esta primera respuesta
    r["armadura"] = historial.resultado_armadura(eval_, conf)
    historial.guardar_armadura(intento_id, r["armadura"])
    r["pista"] = None; r["nivel"] = 0; r["quedan"] = 0
    if eval_ != "correcta":
        ya = it.get("pistas_usadas") or 0
        nivel = max(r.get("nivel_pista") or 1, min(2, ya + 1))   # si ya pidió una pista, la siguiente es la fuerte
        historial.guardar_pista(intento_id, nivel)
        r["pista"] = _pista(caso, nivel); r["nivel"] = nivel; r["quedan"] = 2 - nivel
    r["hechos"] = hechos
    return r


def revisar(intento_id, clave, confianza):
    """Fase final. Devuelve cierre, explicación, sentidos ganados y pregunta de reflexión."""
    it = historial.obtener_intento(intento_id)
    if not it:
        raise KeyError("intento inexistente")
    if not it.get("clave_ini"):
        raise ValueError("Primero hay que decidir")
    if it.get("cierre"):
        raise ValueError("Este intento ya está cerrado")
    casos, _ = motor.cargar_casos()
    caso = casos[it["caso_id"]]
    conf = _validar_conf(confianza)

    # Decisión 2 con error y todavía queda la pista fuerte: se da la pista y se pide una tercera decisión.
    if caso["formato"] != "reflexion_abierta" and not it.get("clave_med"):
        ev2, _t = motor.evaluar_opcion(caso, clave.upper())
        if ev2 != "correcta" and it.get("eval_ini") != "correcta" and (it.get("pistas_usadas") or 0) < 2:
            historial.guardar_media(intento_id, clave.upper(), conf)
            historial.guardar_pista(intento_id, 2)
            return {"accion": "pista_fuerte", "motivo": "sigue_error_tras_pista", "texto_accion": motor.TEXTO_ACCION["pista_fuerte"],
                    "texto_motivo": motor.TEXTO_MOTIVO["sigue_error_tras_pista"], "pista": _pista(caso, 2), "nivel": 2,
                    "continua": True, "diagnosticos": [], "sentidos": []}

    if caso["formato"] == "reflexion_abierta":
        historial.guardar_final(intento_id, "-", conf, "abierta", None, "cerrar_abierta", "formato_abierto",
                                ["justificar"], [])
        return {"accion": "cerrar_abierta", "motivo": "formato_abierto",
                "texto_accion": "Gracias. Tu respuesta la leerá tu maestro o maestra.",
                "texto_motivo": "Caso de reflexión abierta.", "explicacion": caso["explicacion"],
                "sentidos": ["justificar"], "reflexion": None, "diagnosticos": [],
                "habilidad": motor.habilidad_de(caso), "resolucion": "abierta",
                "repeticion": bool(it.get("repeticion")),
                "puntos_equipo": 0 if it.get("repeticion") else historial.puntos_territorio(["justificar"], "abierta", 0)}

    eval_, tipo = motor.evaluar_opcion(caso, clave.upper())
    inicial = {"clave": it["clave_ini"], "confianza": it["conf_ini"], "justificacion": it["just_ini"],
               "evaluacion": it["eval_ini"], "tipo_error": it["tipo_error_ini"]}
    final = {"clave": clave, "confianza": conf, "evaluacion": eval_, "tipo_error": tipo}
    hechos = motor.armar_hechos(caso, "final", inicial, final, ayuda_previa=True)
    r = motor.consultar(hechos)
    # Revisar antes de decidir y acertar también es revisar
    if it.get("reviso_antes") and it["eval_ini"] == "correcta" and "revisar" not in r["sentidos"]:
        r["sentidos"] = sorted(r["sentidos"] + ["revisar"])
    historial.guardar_final(intento_id, clave.upper(), conf, eval_, tipo, r["accion"], r["motivo"], r["sentidos"], r["diagnosticos"])
    r["explicacion"] = caso["explicacion"]
    r["reflexion"] = caso["reflexion"]
    r["habilidad"] = motor.habilidad_de(caso)
    it2 = historial.obtener_intento(intento_id)
    r["pistas_usadas"] = it2.get("pistas_usadas") or 0
    r["resolucion"] = historial.resolucion(it2)
    r["repeticion"] = bool(it2.get("repeticion"))
    acerto_ini, seguro_ini = it["eval_ini"] == "correcta", (it["conf_ini"] or 0) >= historial.SEGURO_DESDE
    r["punteria_caso"] = {"confianza": it["conf_ini"], "acerto": acerto_ini, "coincide": acerto_ini == seguro_ini}
    r["reviso_antes"] = bool(it2.get("reviso_antes"))
    r["armadura"] = it2.get("armadura")
    r["punto_armadura"] = it2.get("punto_armadura") or 0
    r["efecto_racha"] = historial.efecto_racha(r["sentidos"], it["eval_ini"], r["armadura"])
    ayudas = r["pistas_usadas"] - (1 if r["reviso_antes"] else 0)
    r["sin_ayuda"] = eval_ == "correcta" and ayudas <= 0
    r["puntos_equipo"] = 0 if r["repeticion"] else historial.puntos_territorio(r["sentidos"], eval_, ayudas, r["punto_armadura"])
    r["continua"] = False
    r["hechos"] = hechos
    return r


def reflexionar(intento_id, texto):
    it = historial.obtener_intento(intento_id)
    if not it or not it.get("cierre"):
        raise ValueError("La reflexión se escribe al cerrar el caso")
    if it.get("reflexion"):
        raise ValueError("La reflexión ya fue enviada")
    historial.guardar_reflexion(intento_id, texto.strip()[:2000])
    return {"ok": True}


def reportar_duda(intento_id):
    historial.marcar_duda(intento_id)
    return {"ok": True, "mensaje": "Gracias por avisar. El docente revisará este caso."}
