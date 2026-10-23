/* ============================================================
   ticket_manual.js — Formulario de captura manual de tickets
   ============================================================ */

(function () {
    const form = document.getElementById("form-manual");
    if (!form) return;

    const tbody = document.getElementById("filas-manual");
    const plantilla = document.getElementById("fila-manual-template");
    const totalRenglones = document.getElementById("total-renglones");
    const inputRenglones = document.getElementById("renglones-manual");

    const formatoMoneda = new Intl.NumberFormat("es-MX", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    });

    function numero(valor) {
        const n = parseFloat(valor);
        return Number.isFinite(n) ? n : null;
    }

    function opcionesCategorias(seleccionada) {
        const nombres = Object.keys(ARBOL).sort();
        if (seleccionada && seleccionada !== SIN_CATEGORIA && !nombres.includes(seleccionada)) {
            nombres.push(seleccionada);
        }
        return [""].concat(nombres);
    }

    function opcionesSubcategorias(categoria, seleccionada) {
        const subs = (categoria && ARBOL[categoria]) ? ARBOL[categoria].slice() : [];
        if (seleccionada && seleccionada !== SIN_SUBCATEGORIA && !subs.includes(seleccionada)) {
            subs.push(seleccionada);
        }
        return [""].concat(subs.sort());
    }

    function llenarSelect(select, valores, textoVacio, seleccionado) {
        select.innerHTML = "";
        valores.forEach(function (valor) {
            const option = document.createElement("option");
            option.value = valor;
            option.textContent = valor || textoVacio;
            if (valor === seleccionado) option.selected = true;
            select.appendChild(option);
        });
        if (!valores.includes(seleccionado)) select.value = "";
    }

    function actualizarSubcategorias(fila, seleccionada) {
        const categoria = fila.querySelector(".sel-categoria").value;
        const selectSub = fila.querySelector(".sel-subcategoria");
        const valor = seleccionada !== undefined ? seleccionada : selectSub.value;
        llenarSelect(
            selectSub,
            opcionesSubcategorias(categoria, valor),
            "— sin subcategoría —",
            valor
        );
    }

    function autoTotal(fila) {
        const cantidad = numero(fila.querySelector(".inp-cantidad").value);
        const regular = numero(fila.querySelector(".inp-regular").value);
        const promo = numero(fila.querySelector(".inp-promo").value);
        const precio = promo !== null ? promo : regular;
        const total = fila.querySelector(".inp-total");
        if (cantidad !== null && cantidad > 0 && precio !== null && precio >= 0) {
            total.value = (Math.round(cantidad * precio * 100) / 100).toFixed(2);
        }
    }

    function recalcular() {
        let suma = 0;
        tbody.querySelectorAll("tr.fila-manual").forEach(function (fila) {
            const total = numero(fila.querySelector(".inp-total").value);
            if (total !== null) suma += total;
            const categoria = fila.querySelector(".sel-categoria").value;
            const subcategoria = fila.querySelector(".sel-subcategoria").value;
            fila.dataset.match = (
                categoria && categoria !== SIN_CATEGORIA &&
                subcategoria && subcategoria !== SIN_SUBCATEGORIA
            ) ? "1" : "0";
        });
        totalRenglones.textContent = "$" + formatoMoneda.format(suma);
    }

    function crearFila(datos) {
        datos = datos || {};
        const fila = plantilla.content.firstElementChild.cloneNode(true);

        fila.querySelector(".inp-descripcion").value = datos.descripcion || "";
        fila.querySelector(".inp-sku").value = datos.sku || "";
        fila.querySelector(".inp-cantidad").value = datos.cantidad || "1";
        fila.querySelector(".inp-regular").value = datos.precio_regular || "";
        fila.querySelector(".inp-promo").value = datos.precio_promocion || "";
        fila.querySelector(".inp-total").value = datos.total || "";
        fila.querySelector(".chk-producto").checked = datos.registrar_producto !== false;

        const categoria = (!datos.categoria || datos.categoria === SIN_CATEGORIA)
            ? "" : datos.categoria;
        const subcategoria = (!datos.subcategoria || datos.subcategoria === SIN_SUBCATEGORIA)
            ? "" : datos.subcategoria;

        const selectCategoria = fila.querySelector(".sel-categoria");
        llenarSelect(
            selectCategoria,
            opcionesCategorias(categoria),
            "— sin categoría —",
            categoria
        );
        actualizarSubcategorias(fila, subcategoria);

        fila.dataset.totalManual = (
            datos.total !== undefined &&
            datos.total !== null &&
            String(datos.total).trim() !== ""
        ) ? "1" : "0";

        selectCategoria.addEventListener("change", function () {
            actualizarSubcategorias(fila, "");
            recalcular();
        });
        fila.querySelector(".sel-subcategoria").addEventListener("change", recalcular);

        [".inp-cantidad", ".inp-regular", ".inp-promo"].forEach(function (selector) {
            fila.querySelector(selector).addEventListener("input", function () {
                if (fila.dataset.totalManual !== "1") autoTotal(fila);
                recalcular();
            });
        });
        fila.querySelector(".inp-total").addEventListener("input", function () {
            fila.dataset.totalManual = "1";
            recalcular();
        });
        fila.querySelector(".btn-quitar").addEventListener("click", function () {
            fila.remove();
            if (!tbody.querySelector("tr.fila-manual")) crearFila({});
            recalcular();
        });

        if (fila.dataset.totalManual !== "1") autoTotal(fila);
        tbody.appendChild(fila);
        recalcular();
        return fila;
    }

    function serializar() {
        const filas = [];
        tbody.querySelectorAll("tr.fila-manual").forEach(function (fila) {
            const descripcion = fila.querySelector(".inp-descripcion").value.trim();
            const sku = fila.querySelector(".inp-sku").value.trim();
            const cantidad = fila.querySelector(".inp-cantidad").value.trim();
            const regular = fila.querySelector(".inp-regular").value.trim();
            const promo = fila.querySelector(".inp-promo").value.trim();
            const total = fila.querySelector(".inp-total").value.trim();
            const categoria = fila.querySelector(".sel-categoria").value.trim();
            const subcategoria = fila.querySelector(".sel-subcategoria").value.trim();
            const registrar = fila.querySelector(".chk-producto").checked;

            // Las filas completamente vacías se ignoran; una fila con algún
            // dato pero sin descripción sí es un error de captura.
            if (!descripcion && !sku && !regular && !promo && !total) return;

            filas.push({
                descripcion: descripcion,
                sku: sku,
                cantidad: cantidad,
                precio_regular: regular,
                precio_promocion: promo,
                total: total,
                categoria: categoria,
                subcategoria: subcategoria,
                registrar_producto: registrar,
            });
        });
        return filas;
    }

    document.getElementById("btn-agregar-fila").addEventListener("click", function () {
        const fila = crearFila({});
        fila.querySelector(".inp-descripcion").focus();
    });

    form.addEventListener("submit", function (evento) {
        const filas = serializar();
        if (!filas.length) {
            evento.preventDefault();
            window.alert("Agrega al menos un renglón con descripción.");
            return;
        }

        const faltantes = [];
        tbody.querySelectorAll("tr.fila-manual").forEach(function (fila, indice) {
            const descripcion = fila.querySelector(".inp-descripcion").value.trim();
            const sku = fila.querySelector(".inp-sku").value.trim();
            const regular = fila.querySelector(".inp-regular").value.trim();
            const promo = fila.querySelector(".inp-promo").value.trim();
            const total = fila.querySelector(".inp-total").value.trim();
            if (!descripcion && !sku && !regular && !promo && !total) return;

            const cantidad = numero(fila.querySelector(".inp-cantidad").value);
            if (!descripcion) {
                faltantes.push("renglón " + (indice + 1) + " sin descripción");
            }
            if (cantidad === null || cantidad <= 0) {
                faltantes.push("renglón " + (indice + 1) + " con cantidad inválida");
            }
        });
        if (faltantes.length) {
            evento.preventDefault();
            window.alert("Revisa la captura:\n• " + faltantes.join("\n• "));
            return;
        }

        inputRenglones.value = JSON.stringify(filas);
    });

    const iniciales = Array.isArray(FILAS_INICIALES) && FILAS_INICIALES.length
        ? FILAS_INICIALES
        : [{}];
    iniciales.forEach(function (datos) {
        crearFila(datos);
    });
})();
