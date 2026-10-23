/* ============================================================
   utilidades.js — Funciones compartidas entre módulos
   ============================================================ */

/**
 * Escapa HTML para prevenir XSS al insertar contenido dinámico.
 */
function escaparHTML(valor) {
    const div = document.createElement("div");
    div.textContent = valor == null ? "" : String(valor);
    return div.innerHTML;
}

/**
 * Formatea un número como moneda mexicana.
 */
function formatoMoneda(valor) {
    return "$ " + (valor || 0).toLocaleString("es-MX", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    });
}

/**
 * Realiza una petición fetch y devuelve el JSON parseado.
 * Lanza error si la respuesta no es OK.
 */
async function fetchJSON(url, opciones = {}) {
    const respuesta = await fetch(url, opciones);
    // La sesión venció mientras la pantalla seguía abierta: volver al login.
    if (respuesta.status === 401) {
        window.location.href = "/login?siguiente=" + encodeURIComponent(location.pathname + location.search);
        throw new Error("Sesión vencida");
    }
    if (!respuesta.ok) {
        throw new Error(`HTTP ${respuesta.status}: ${respuesta.statusText}`);
    }
    return respuesta.json();
}

/**
 * Muestra un mensaje de confirmación nativo.
 */
function confirmar(mensaje) {
    return window.confirm(mensaje);
}

/**
 * Muestra una alerta nativa.
 */
function alertar(mensaje) {
    window.alert(mensaje);
}

/**
 * Debounce para limitar la frecuencia de ejecución de una función.
 */
function debounce(func, espera) {
    let timeout;
    return function (...args) {
        clearTimeout(timeout);
        timeout = setTimeout(() => func.apply(this, args), espera);
    };
}
