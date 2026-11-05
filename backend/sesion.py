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


def abrir(seudonimo, caso_id):
    casos, _ = motor.cargar_casos()
    caso = casos[caso_id]
    abierto = historial.intento_abierto(seudonimo, caso_id)
    intento_id = abierto["id"] if abierto else historial.abrir_intento(seudonimo, caso_id, caso.get("familia_error"))
    return {"intento_id": intento_id, "caso": motor.caso_para_alumno(caso),
            "retomado": bool(abierto and abierto.get("clave_ini"))}


def responder(intento_id, clave, confianza, justificacion=""):
    """Fase inicial. Devuelve la intervención del tutor (pista + motivo)."""
    it = historial.obtener_intento(intento_id)
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
    hechos = motor.armar_hechos(caso, "inicial", inicial, historial_errores=historial.errores_previos(it["seudonimo"]))
    r = motor.consultar(hechos)
    historial.guardar_inicial(intento_id, clave.upper(), conf, justificacion, eval_, tipo, r["accion"], r["motivo"])
    r["pista"] = caso["pista"] if eval_ != "correcta" else None
    r["hechos"] = hechos
    return r


def revisar(intento_id, clave, confianza):
    """Fase final. Devuelve cierre, explicación, sentidos ganados y pregunta de reflexión."""
    it = historial.obtener_intento(intento_id)
    casos, _ = motor.cargar_casos()
    caso = casos[it["caso_id"]]
    conf = _validar_conf(confianza)

    if caso["formato"] == "reflexion_abierta":
        historial.guardar_final(intento_id, "-", conf, "abierta", None, "cerrar_abierta", "formato_abierto",
                                ["justificar"], [])
        return {"accion": "cerrar_abierta", "motivo": "formato_abierto",
                "texto_accion": "Gracias. Tu respuesta la leerá tu maestro o maestra.",
                "texto_motivo": "Caso de reflexión abierta.", "explicacion": caso["explicacion"],
                "sentidos": ["justificar"], "reflexion": None, "diagnosticos": []}

    eval_, tipo = motor.evaluar_opcion(caso, clave.upper())
    inicial = {"clave": it["clave_ini"], "confianza": it["conf_ini"], "justificacion": it["just_ini"],
               "evaluacion": it["eval_ini"], "tipo_error": it["tipo_error_ini"]}
    final = {"clave": clave, "confianza": conf, "evaluacion": eval_, "tipo_error": tipo}
    hechos = motor.armar_hechos(caso, "final", inicial, final, ayuda_previa=True)
    r = motor.consultar(hechos)
    historial.guardar_final(intento_id, clave.upper(), conf, eval_, tipo, r["accion"], r["motivo"], r["sentidos"], r["diagnosticos"])
    r["explicacion"] = caso["explicacion"]
    r["reflexion"] = caso["reflexion"]
    r["hechos"] = hechos
    return r


def reflexionar(intento_id, texto):
    historial.guardar_reflexion(intento_id, texto)
    return {"ok": True}


def reportar_duda(intento_id):
    historial.marcar_duda(intento_id)
    return {"ok": True, "mensaje": "Gracias por avisar. El docente revisará este caso."}
