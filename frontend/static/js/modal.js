/* ============================================================
   modal.js — Lógica genérica de modales de confirmación
   ============================================================ */

let modalCallback = null;

/**
 * Abre una modal de confirmación con un input editable.
 *
 * @param {Object} opciones
 * @param {string} opciones.titulo - Título de la modal
 * @param {string} opciones.mensaje - Mensaje descriptivo
 * @param {string} [opciones.valorInicial] - Valor inicial del input
 * @param {string} [opciones.placeholder] - Placeholder del input
 * @param {Function} opciones.onConfirmar - Callback con el valor confirmado
 */
function abrirModal({ titulo, mensaje, valorInicial = "", placeholder = "", onConfirmar }) {
    document.getElementById("modal-titulo").textContent = titulo;
    document.getElementById("modal-mensaje").textContent = mensaje;

    const input = document.getElementById("modal-input");
    input.value = valorInicial;
    input.placeholder = placeholder;

    modalCallback = onConfirmar;

    document.getElementById("modal-confirmacion").hidden = false;
    input.focus();
}

/**
 * Cierra la modal y limpia el callback.
 */
function cerrarModal() {
    document.getElementById("modal-confirmacion").hidden = true;
    modalCallback = null;
}

/**
 * Confirma la modal con el valor actual del input.
 */
function confirmarModal() {
    const valor = document.getElementById("modal-input").value.trim();
    if (modalCallback) {
        modalCallback(valor);
    }
    cerrarModal();
}

/**
 * Inicializa los eventos de la modal.
 * Debe llamarse una vez al cargar la página.
 */
function inicializarModal() {
    document.getElementById("modal-confirmar").addEventListener("click", confirmarModal);
    document.getElementById("modal-cancelar").addEventListener("click", cerrarModal);

    // Cerrar al hacer clic fuera de la modal
    document.getElementById("modal-confirmacion").addEventListener("click", (e) => {
        if (e.target.id === "modal-confirmacion") {
            cerrarModal();
        }
    });

    // Cerrar con Escape
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && !document.getElementById("modal-confirmacion").hidden) {
            cerrarModal();
        }
    });
}
