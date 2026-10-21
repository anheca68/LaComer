/* ============================================================
   validacion.js — Validación de formularios de tickets
   ============================================================ */

/**
 * Verifica si un valor es una opción personalizada creada por el usuario
 * (no existe en el árbol de categorías pero está en el select).
 */
function esOpcionPersonalizada(select, valor) {
    if (!valor) return false;
    // Si el valor existe como opción en el select pero no en el árbol,
    // es una opción personalizada
    const opciones = Array.from(select.options).map(o => o.value);
    return opciones.includes(valor) && !ARBOL[valor];
}

/**
 * Verifica si una fila de la tabla de revisión es válida.
 * Una fila es válida si tiene categoría y subcategoría completas.
 */
function esValido(fila) {
    const selCategoria = fila.querySelector(".sel-categoria");
    const selSubcategoria = fila.querySelector(".sel-subcategoria");
    const categoria = selCategoria.value.trim();
    const subcategoria = selSubcategoria.value.trim();

    if (!categoria || categoria === SIN_CATEGORIA) {
        return false;
    }
    // Válido si existe en el árbol O si es una opción personalizada
    if (!ARBOL[categoria] && !esOpcionPersonalizada(selCategoria, categoria)) {
        return false;
    }

    if (!subcategoria || subcategoria === SIN_SUBCATEGORIA) {
        return false;
    }
    if (!esOpcionPersonalizada(selSubcategoria, subcategoria) &&
        !(ARBOL[categoria] || []).includes(subcategoria)) {
        return false;
    }

    return true;
}

/**
 * Actualiza la clase visual de una fila según su validez.
 */
function revalidarFila(fila) {
    const valido = esValido(fila);
    fila.classList.toggle("sin-match", !valido);
    fila.classList.toggle("validado", valido);

    const estado = fila.querySelector(".estado");
    const editado = fila.dataset.match === "0";
    estado.innerHTML = valido
        ? (editado ? '<span class="badge-ok">corregido</span>' : "")
        : (editado ? '<span class="badge-alerta">sin categoría</span>' : "");
}

/**
 * Actualiza los contadores de validación de un ticket.
 */
function actualizarContadores(revision) {
    const filas = Array.from(revision.querySelectorAll("tbody tr"));
    const pendientes = filas.filter(fila => !esValido(fila)).length;
    const validados = filas.length - pendientes;

    revision.querySelectorAll(".cont-pendientes")
        .forEach(span => span.textContent = pendientes);
    revision.querySelectorAll(".cont-validados")
        .forEach(span => span.textContent = validados);
    revision.querySelectorAll(".cont-total")
        .forEach(span => span.textContent = filas.length);
    revision.querySelectorAll(".barra-avance")
        .forEach(barra => {
            const pct = filas.length ? Math.round(validados * 100 / filas.length) : 0;
            barra.style.width = pct + "%";
        });
}
