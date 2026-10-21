/* ============================================================
   catalogo.js — Lógica del catálogo de productos
   ============================================================ */

const NUEVA = "__nueva__";

/**
 * Genera las opciones del select de categorías.
 */
function opcionesCategorias(seleccionada) {
    const nombres = Object.keys(ARBOL).concat([SIN_CATEGORIA]).sort();
    return `<option value="">— sin categoría —</option>` +
        nombres.map(nombre =>
            `<option value="${escaparHTML(nombre)}"${nombre === seleccionada ? " selected" : ""}>${escaparHTML(nombre)}</option>`
        ).join("") +
        `<option value="${NUEVA}">+ nueva…</option>`;
}

/**
 * Genera las opciones del select de subcategorías.
 */
function opcionesSubcategorias(categoria, seleccionada, permitirNueva) {
    const subs = categoria && ARBOL[categoria] ? ARBOL[categoria] : [];
    let permitidas = [""].concat(subs);
    if (seleccionada && permitidas.indexOf(seleccionada) === -1) {
        seleccionada = "";
    }
    return `<option value="">— sin subcategoría —</option>` +
        subs.map(nombre =>
            `<option value="${escaparHTML(nombre)}"${nombre === seleccionada ? " selected" : ""}>${escaparHTML(nombre)}</option>`
        ).join("") +
        (permitirNueva ? `<option value="${NUEVA}">+ nueva…</option>` : "");
}

/**
 * Agrega una opción personalizada a un select y la selecciona.
 */
function agregarOpcionPersonalizada(select, valor) {
    const option = document.createElement("option");
    option.value = valor;
    option.textContent = valor;
    select.appendChild(option);
    select.value = valor;
}

/**
 * Inicializa la página del catálogo.
 */
function inicializarCatalogo() {
    // Inicializar modal
    inicializarModal();

    // Inicializar cada fila de producto
    document.querySelectorAll("tbody tr").forEach(fila => {
        const selCategoria = fila.querySelector(".sel-categoria");
        const selSubcategoria = fila.querySelector(".sel-subcategoria");

        // Poblar selects
        selCategoria.innerHTML = opcionesCategorias(fila.dataset.categoria);
        selSubcategoria.innerHTML = opcionesSubcategorias(
            fila.dataset.categoria, fila.dataset.subcategoria, true
        );

        // Evento: cambio de categoría
        selCategoria.addEventListener("change", () => {
            if (selCategoria.value === NUEVA) {
                abrirModal({
                    titulo: "Nueva categoría",
                    mensaje: "Se creará una nueva categoría en el catálogo:",
                    valorInicial: "",
                    placeholder: "Nombre de la categoría",
                    onConfirmar: (nombre) => {
                        if (!nombre) {
                            selCategoria.value = "";
                            return;
                        }
                        agregarOpcionPersonalizada(selCategoria, nombre);
                        selSubcategoria.innerHTML = opcionesSubcategorias(null, "", true);
                    }
                });
            } else {
                selSubcategoria.innerHTML = opcionesSubcategorias(selCategoria.value, "", true);
            }
        });

        // Evento: cambio de subcategoría
        selSubcategoria.addEventListener("change", () => {
            if (selSubcategoria.value === NUEVA) {
                const categoria = selCategoria.value;
                abrirModal({
                    titulo: "Nueva subcategoría",
                    mensaje: `Se creará una nueva subcategoría dentro de "${categoria}":`,
                    valorInicial: "",
                    placeholder: "Nombre de la subcategoría",
                    onConfirmar: (nombre) => {
                        if (!nombre) {
                            selSubcategoria.value = "";
                            return;
                        }
                        agregarOpcionPersonalizada(selSubcategoria, nombre);
                    }
                });
            }
        });

        // Validación antes de enviar
        fila.querySelector(".fila-reclasificar").addEventListener("submit", evento => {
            const categoria = selCategoria.value.trim();
            if (!categoria) {
                evento.preventDefault();
                alertar("Elige una categoría antes de guardar.");
            }
        });
    });

    // Búsqueda con debounce
    const inputBusqueda = document.getElementById("buscar");
    if (inputBusqueda) {
        inputBusqueda.addEventListener("input", debounce(() => {
            const params = new URLSearchParams(window.location.search);
            params.set("buscar", inputBusqueda.value);
            window.location.search = params.toString();
        }, 300));
    }

    // Filtro por categoría
    const selectCategoria = document.getElementById("categoria");
    if (selectCategoria) {
        selectCategoria.addEventListener("change", () => {
            const params = new URLSearchParams(window.location.search);
            if (selectCategoria.value) {
                params.set("categoria", selectCategoria.value);
            } else {
                params.delete("categoria");
            }
            window.location.search = params.toString();
        });
    }
}

// Inicializar cuando el DOM esté listo
if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", inicializarCatalogo);
} else {
    inicializarCatalogo();
}
