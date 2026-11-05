// api.js — llamadas a la API y sesión del alumno (localStorage)
const API = '/api';

async function api(ruta, metodo = 'GET', cuerpo = null, cabeceras = {}) {
  const opciones = { method: metodo, headers: { 'Content-Type': 'application/json', ...cabeceras } };
  if (cuerpo) opciones.body = JSON.stringify(cuerpo);
  const r = await fetch(API + ruta, opciones);
  const datos = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(datos.detail || `Error ${r.status}`);
  return datos;
}

const Sesion = {
  leer() {
    try { return JSON.parse(localStorage.getItem('ss_alumno') || 'null'); } catch { return null; }
  },
  guardar(alumno) {
    try { localStorage.setItem('ss_alumno', JSON.stringify(alumno)); } catch {}
  },
  borrar() {
    try { localStorage.removeItem('ss_alumno'); } catch {}
  },
  // Mapa (materia) en el que está trabajando el alumno dentro de su grupo
  mapa() { const a = Sesion.leer(); return a && a.mapa ? a.mapa : null; },
  elegirMapa(id) { const a = Sesion.leer(); if (!a) return; a.mapa = id; Sesion.guardar(a); },
  // Asegura que el alumno tenga la lista de mapas de su grupo y un mapa elegido
  async conMapas() {
    const a = Sesion.leer(); if (!a) return null;
    if (a.grupo && (!a.mapas || !a.mapas.length)) {
      try { const g = await api(`/grupo/${a.grupo}`); a.mapas = g.mapas || []; a.grupo_nombre = g.nombre; } catch {}
    }
    if (a.mapas && a.mapas.length && !a.mapas.some(m => m.id === a.mapa)) a.mapa = a.mapas[0].id;
    Sesion.guardar(a);
    return a;
  },
};

const ESCUDO = e => `assets/equipos/${e}.png`;
const escudoHtml = (e, cls = 'escudo') => `<img class="${cls}" src="${ESCUDO(e)}" alt="Equipo ${e}" onerror="this.replaceWith(Object.assign(document.createElement('span'),{className:'ficha-equipo ${e}'}))">`;

function toast(msg, ms = 2500) {
  const t = document.createElement('div');
  t.className = 'toast';
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), ms);
}

function pintarCabecera(alumno, sentidos) {
  const el = document.getElementById('jugador');
  if (!el) return;
  if (!alumno) { el.innerHTML = ''; return; }
  el.innerHTML = `
    ${escudoHtml(alumno.equipo)}
    <span>${alumno.seudonimo}</span>
    <span class="sentidos-pill">${sentidos ?? 0}<small>sentidos</small></span>
    <button class="btn btn-enlace" id="salir">salir</button>`;
  document.getElementById('salir').onclick = () => { Sesion.borrar(); location.href = 'index.html'; };
}
