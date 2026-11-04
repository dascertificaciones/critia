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
};

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
    <span class="ficha-equipo ${alumno.equipo}"></span>
    <span>${alumno.seudonimo}</span>
    <span class="sentidos-pill">${sentidos ?? 0} sentidos</span>
    <button class="btn btn-enlace" id="salir">salir</button>`;
  document.getElementById('salir').onclick = () => { Sesion.borrar(); location.href = 'index.html'; };
}
