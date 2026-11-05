"""
critia.py — Critia (consola)
Uso:
    python critia.py --alumno seudonimo01 --equipo rojo --caso ABC-ESC-002
    python critia.py --alumno seudonimo01 --equipo rojo            (recorre todos los casos)
"""
import argparse
import motor
import historial
import sesion

ACERCA = """
SOBRE ESTE TUTOR
Puedo ayudarte a practicar cómo revisar afirmaciones y decidir qué evidencia
hace falta. Uso ejercicios escritos por personas y reglas explícitas.
No puedo verificar todo lo que hay en internet, ni saber cómo piensas,
ni sustituir a tu maestro o maestra. Si algo involucra tu seguridad, tu
privacidad o consecuencias serias, consulta a una persona de confianza.
"""


def pedir(msg, validar=None):
    while True:
        v = input(msg).strip()
        try:
            return validar(v) if validar else v
        except Exception as e:
            print(f"  ({e})")


def correr_caso(seudonimo, caso_id):
    a = sesion.abrir(seudonimo, caso_id)
    c = a["caso"]
    print(f"\n{'='*60}\nCRITIA | Misión {c['mision']} | Caso {c['id']}: {c['titulo']}")
    if c["provisional"]:
        print("(caso provisional: aún no revisado por el docente)")
    print(f"{'='*60}\n{c['situacion']}\n\n{c['pregunta']}")
    for o in c["opciones"]:
        print(f"  {o['clave']}) {o['texto']}")
    claves = [o["clave"] for o in c["opciones"]]

    if c["formato"] == "reflexion_abierta":
        texto = pedir("\nTu respuesta: ")
        conf = pedir("Confianza (0-100): ", lambda v: int(v) if 0 <= int(v) <= 100 else 1 / 0)
        sesion.responder(a["intento_id"], "-", conf, texto)
        r = sesion.revisar(a["intento_id"], "-", conf)
        sesion.reflexionar(a["intento_id"], texto)
        print(f"\nTutor: {r['texto_accion']}\n{r['explicacion']}")
        return

    clave = pedir("\nTu respuesta (letra, o ? si crees que el caso está mal): ",
                  lambda v: v.upper() if v.upper() in claves + ["?"] else 1 / 0)
    if clave == "?":
        sesion.reportar_duda(a["intento_id"])
        clave = pedir("Aun así, elige una: ", lambda v: v.upper() if v.upper() in claves else 1 / 0)
    conf = pedir("Confianza (0-100): ", lambda v: int(v) if 0 <= int(v) <= 100 else 1 / 0)
    just = pedir("Justifica en una línea (opcional): ")

    r = sesion.responder(a["intento_id"], clave, conf, just)
    print(f"\nTutor: {r['texto_accion']}")
    print(f"Motivo: {r['texto_motivo']}")
    if r.get("pista"):
        print(f"Pista: {r['pista']}")

    clave2 = pedir("\nRespuesta revisada: ", lambda v: v.upper() if v.upper() in claves else 1 / 0)
    conf2 = pedir("Confianza revisada (0-100): ", lambda v: int(v) if 0 <= int(v) <= 100 else 1 / 0)

    r2 = sesion.revisar(a["intento_id"], clave2, conf2)
    print(f"\nTutor: {r2['texto_accion']}")
    print(f"Motivo: {r2['texto_motivo']}")
    print(f"\nExplicación:\n{r2['explicacion']}")
    print(f"\nSentidos ganados: {', '.join(r2['sentidos']) or 'ninguno'} ({len(r2['sentidos'])}/3)")
    print(f"[accion={r2['accion']} motivo={r2['motivo']}]")
    if r2.get("reflexion"):
        texto = pedir(f"\nReflexión: {r2['reflexion']}\n> ")
        if texto:
            sesion.reflexionar(a["intento_id"], texto)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--alumno", required=True)
    p.add_argument("--equipo", default="rojo")
    p.add_argument("--caso")
    args = p.parse_args()

    historial.registrar_alumno(args.alumno, args.equipo)
    print(ACERCA)
    casos, _ = motor.cargar_casos()
    ids = [args.caso] if args.caso else sorted(casos, key=lambda i: (casos[i]["mision"], i))
    for cid in ids:
        correr_caso(args.alumno, cid)
    prog = historial.progreso_alumno(args.alumno)
    print(f"\nTotal de sentidos: {prog['sentidos_total']}")


if __name__ == "__main__":
    main()
