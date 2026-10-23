/* ============================================================
   tickets.js — Lógica específica de la página de tickets
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
 * Actualiza el árbol de categorías desde el servidor.
 * Se llama después de crear una categoría o subcategoría nueva.
 */
async function actualizarArbolCategorias() {
    try {
        const respuesta = await fetch("/api/categorias");
        const datos = await respuesta.json();
        if (datos.arbol) {
            // Actualizar el objeto ARBOL global
            Object.keys(ARBOL).forEach(k => delete ARBOL[k]);
            Object.assign(ARBOL, datos.arbol);
        }
    } catch (e) {
        console.error("No se pudo actualizar el árbol de categorías", e);
    }
}

/**
 * Inicializa la página de tickets.
 */
function inicializarTickets() {
    // Inicializar modal
    inicializarModal();

    // Inicializar cada ticket en revisión
    document.querySelectorAll(".ticket-revision").forEach(revision => {
        revision.querySelectorAll("tbody tr").forEach(fila => {
            const selCategoria = fila.querySelector(".sel-categoria");
            const selSubcategoria = fila.querySelector(".sel-subcategoria");

            // Poblar selects
            selCategoria.innerHTML = opcionesCategorias(fila.dataset.categoria);
            selSubcategoria.innerHTML = opcionesSubcategorias(
                fila.dataset.categoria, fila.dataset.subcategoria, true
            );

            // Evento: cambio de categoría
            selCategoria.addEventListener("change", async () => {
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
                            // Actualizar árbol global con la nueva categoría
                            ARBOL[nombre] = [];
                        }
                    });
                } else {
                    selSubcategoria.innerHTML = opcionesSubcategorias(selCategoria.value, "", true);
                }
                revalidarFila(fila);
                actualizarContadores(revision);
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
                            // Actualizar árbol global con la nueva subcategoría
                            if (!ARBOL[categoria]) {
                                ARBOL[categoria] = [];
                            }
                            if (!ARBOL[categoria].includes(nombre)) {
                                ARBOL[categoria].push(nombre);
                            }
                        }
                    });
                }
                revalidarFila(fila);
                actualizarContadores(revision);
            });

            revalidarFila(fila);
        });
        actualizarContadores(revision);
    });

    // Botón alternar checkboxes
    document.querySelectorAll(".btn-alternar-chk").forEach(boton => {
        boton.addEventListener("click", () => {
            const casillas = Array.from(boton.closest(".ticket-revision")
                .querySelectorAll(".chk-producto"));
            const marcar = casillas.some(c => !c.checked);
            casillas.forEach(c => c.checked = marcar);
            boton.textContent = marcar
                ? "Desmarcar todas las casillas"
                : "Marcar todas las casillas";
        });
    });

    // Envío de formulario de confirmación
    document.querySelectorAll(".form-confirmar").forEach(form => {
        form.addEventListener("submit", evento => {
            const invalidas = Array.from(form.querySelectorAll("tbody tr"))
                .filter(fila => !esValido(fila));

            const esGuardar = evento.submitter
                && evento.submitter.classList.contains("btn-guardar");
            const total = form.querySelectorAll("tbody tr").length;

            if (invalidas.length && !esGuardar) {
                evento.preventDefault();
                const detalle = invalidas.slice(0, 5).map(fila => {
                    const celda = fila.querySelector(".col-articulo");
                    const nombre = celda ? celda.textContent.trim() : "artículo";
                    return `• ${nombre}`;
                }).join("\n");
                const resto = invalidas.length > 5
                    ? `\n• …y ${invalidas.length - 5} más` : "";
                alertar(
                    "No se puede confirmar: " +
                    `${invalidas.length} de ${total} artículo(s) sin categoría ` +
                    "y subcategoría.\n\n" +
                    "Puedes darle «Guardar cambios» para no perder el avance.\n\n" +
                    `${detalle}${resto}`
                );
                if (typeof invalidas[0].scrollIntoView === "function") {
                    invalidas[0].scrollIntoView({ behavior: "smooth", block: "center" });
                }
                return;
            }

            const correcciones = [];
            form.querySelectorAll("tbody tr").forEach(fila => {
                const chk = fila.querySelector(".chk-producto");
                correcciones.push({
                    indice: Number(fila.dataset.indice),
                    categoria: fila.querySelector(".sel-categoria").value.trim(),
                    subcategoria: fila.querySelector(".sel-subcategoria").value.trim(),
                    registrar_producto: chk ? chk.checked : false
                });
            });
            form.querySelector(".input-correcciones").value = JSON.stringify(correcciones);
        });
    });

    // Formulario de descartar
    document.querySelectorAll(".form-descartar").forEach(form => {
        form.addEventListener("submit", evento => {
            const revision = form.closest(".ticket-revision");
            const mensaje = revision && revision.dataset.origen === "manual"
                ? "¿Descartar esta captura manual? No se registrará en la base ni se generará CSV."
                : "¿Descartar este ticket? El PDF se moverá a descartados/ y NO se generará CSV.";
            if (!confirmar(mensaje)) {
                evento.preventDefault();
            }
        });
    });
}

// Inicializar cuando el DOM esté listo
if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", inicializarTickets);
} else {
    inicializarTickets();
}
