/* ============================================================
   panel.js — Lógica del dashboard (gráficas, fetch de datos)
   ============================================================ */

(function () {
    "use strict";

    // Radio de las esquinas de las barras: redondeadas, pero discretas.
    const RADIO_BARRA = 4;

    // Colores del tema activo (variables de base.css). Se leen al dibujar, así
    // que al cambiar de tema basta con volver a dibujar.
    const tema = (v) => (window.colorTema ? window.colorTema(v) : "");
    function paleta() {
        return {
            principal: tema("--grafica-1"),   // esmeralda
            secundario: tema("--grafica-2"),  // índigo
            descuento: tema("--grafica-3"),   // ámbar
            neutro: tema("--grafica-neutra"),
            rejilla: tema("--grafica-rejilla"),
            texto: tema("--grafica-texto"),
        };
    }
    let PALETA = paleta();

    // Apariencia común de todas las gráficas.
    function estiloGeneral() {
        if (!window.Chart) return;
        const d = window.Chart.defaults;
        d.font.family = getComputedStyle(document.body).fontFamily;
        d.color = PALETA.texto;
        d.borderColor = PALETA.rejilla;
        d.plugins.tooltip.backgroundColor = "#0f172a";
        d.plugins.tooltip.titleColor = "#f8fafc";
        d.plugins.tooltip.bodyColor = "#e2e8f0";
        d.plugins.tooltip.padding = 10;
        d.plugins.tooltip.cornerRadius = 8;
        d.plugins.tooltip.boxPadding = 4;
        d.plugins.legend.labels.usePointStyle = true;
        d.plugins.legend.labels.pointStyle = "rectRounded";
    }

    // Transparencia sobre un color hexadecimal (#rrggbb + aa).
    const alfa = (hex, aa) => hex + aa;

    // Recorta etiquetas largas: sin esto una descripción de 40 caracteres se
    // come el ancho del gráfico y empuja las barras fuera del área visible.
    const recortar = (valores, largo) =>
        valores.map((v) => {
            const t = String(v);
            return t.length > largo ? t.slice(0, largo - 1) + "…" : t;
        });

    const ejeDinero = {
        beginAtZero: true,
        border: { display: false },
        grid: { color: () => PALETA.rejilla },
        ticks: {
            font: { size: 11 },
            callback: (v) => "$ " + v.toLocaleString("es-MX"),
        },
    };

    // Gráficas vivas, para destruirlas y redibujarlas al cambiar de tema.
    const graficas = [];

    // Un canvas en blanco suele ser un canvas sin datos, no un canvas roto. Este
    // aviso en la tarjeta deja claro cuál de las dos cosas pasó.
    function avisar(id, texto) {
        const cv = document.getElementById(id);
        if (!cv || cv.parentNode.querySelector(".vacio")) return;
        const nota = document.createElement("p");
        nota.className = "vacio";
        nota.style.marginTop = "10px";
        nota.textContent = texto;
        cv.parentNode.appendChild(nota);
    }

    function pintar(id, config) {
        const cv = document.getElementById(id);
        if (!cv) {
            console.warn("panel: no existe el canvas", id);
            return;
        }
        if (!window.Chart) {
            avisar(id, "No se cargó la librería de gráficas.");
            return;
        }
        try {
            graficas.push(new window.Chart(cv, config));
        } catch (e) {
            console.error("panel: falló la gráfica", id, e);
            avisar(id, "No se pudo dibujar esta gráfica.");
        }
    }

    // ── Serie principal: bruto y neto como barras, descuentos como línea ─────
    // El backend decide la granularidad: con un mes filtrado la serie viene por
    // día y trae `dia` en vez de `mes`. Se normaliza a `etiqueta` para que la
    // gráfica no tenga que saber de dónde vinieron los datos.
    function serieEtiquetas(serie) {
        return serie.map((r) =>
            r.etiqueta !== undefined
                ? r.etiqueta
                : r.mes !== undefined
                ? r.mes
                : r.dia
        );
    }

    function graficaPeriodo(serie) {
        pintar("g-mes", {
            type: "bar",
            data: {
                labels: serieEtiquetas(serie),
                datasets: [
                    {
                        label: "Bruto",
                        data: serie.map((m) => m.bruto),
                        backgroundColor: PALETA.neutro,
                        borderRadius: RADIO_BARRA,
                        maxBarThickness: 36,
                        order: 3,
                    },
                    {
                        label: "Neto",
                        data: serie.map((m) => m.neto),
                        backgroundColor: PALETA.principal,
                        borderRadius: RADIO_BARRA,
                        maxBarThickness: 36,
                        order: 2,
                    },
                    {
                        label: "Descuentos",
                        data: serie.map((m) => m.descuentos),
                        type: "line",
                        borderColor: PALETA.descuento,
                        backgroundColor: PALETA.descuento,
                        borderWidth: 2,
                        pointRadius: 3,
                        tension: 0.3,
                        // Sin descuentos la línea queda pegada al eje y se lee
                        // como un error de dibujo.
                        hidden: !serie.some((m) => m.descuentos > 0),
                        order: 1,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: "index", intersect: false },
                plugins: {
                    legend: {
                        position: "top",
                        align: "end",
                        labels: { boxWidth: 8, boxHeight: 8, font: { size: 12 } },
                    },
                    tooltip: {
                        callbacks: {
                            label: (c) => " " + c.dataset.label + ": " + formatoMoneda(c.parsed.y),
                        },
                    },
                },
                scales: {
                    x: { grid: { display: false }, border: { display: false } },
                    y: ejeDinero,
                },
            },
        });
    }

    // ── Categorías: barra horizontal, la lectura más rápida de "en qué se va" ──
    function graficaCategoria(cats) {
        // `orden` va de menor a mayor porque Chart.js apila las barras de abajo
        // hacia arriba: al invertirlo la categoría más cara queda arriba.
        const orden = cats.slice().reverse();
        pintar("g-categoria", {
            type: "bar",
            data: {
                labels: recortar(orden.map((c) => c.categoria), 24),
                datasets: [
                    {
                        label: "Gasto",
                        data: orden.map((c) => c.importe),
                        // El importe mayor es el último índice de `orden`: ese
                        // sale en azul intenso y el resto se aclara, para que la
                        // barra más larga sea también la más oscura.
                        backgroundColor: (ctx) =>
                            ctx.dataIndex === orden.length - 1
                                ? PALETA.principal
                                : alfa(PALETA.principal, "99"),
                        borderRadius: RADIO_BARRA,
                        maxBarThickness: 18,
                    },
                ],
            },
            options: {
                indexAxis: "y",
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (c) =>
                                " " +
                                formatoMoneda(c.parsed.x) +
                                "  ·  " +
                                orden[c.dataIndex].porcentaje +
                                "%",
                            title: (items) => orden[items[0].dataIndex].categoria,
                        },
                    },
                },
                scales: {
                    x: ejeDinero,
                    y: {
                        grid: { display: false },
                        border: { display: false },
                        ticks: { font: { size: 11 }, autoSkip: false },
                    },
                },
            },
        });
    }

    // ── Subcategorías ─────────────────────────────────────────────────────────
    function graficaSubcategoria(subs) {
        const orden = subs.slice().reverse();
        pintar("g-subcategoria", {
            type: "bar",
            data: {
                labels: recortar(orden.map((s) => s.subcategoria), 30),
                datasets: [
                    {
                        label: "Gasto",
                        data: orden.map((s) => s.importe),
                        backgroundColor: alfa(PALETA.secundario, "cc"),
                        borderRadius: RADIO_BARRA,
                        maxBarThickness: 22,
                    },
                ],
            },
            options: {
                indexAxis: "y",
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (c) =>
                                " " +
                                formatoMoneda(c.parsed.x) +
                                "  ·  " +
                                orden[c.dataIndex].porcentaje +
                                "%",
                            title: (items) =>
                                orden[items[0].dataIndex].subcategoria +
                                " (" +
                                orden[items[0].dataIndex].categoria +
                                ")",
                        },
                    },
                },
                scales: {
                    x: ejeDinero,
                    y: { grid: { display: false }, border: { display: false }, ticks: { font: { size: 11 } } },
                },
            },
        });
    }

    // ── Día de la semana: el objetivo es ver el patrón, no el detalle ─────────
    function graficaDiaSemana(dias) {
        const mayor = Math.max(...dias.map((d) => d.importe));
        pintar("g-dia", {
            type: "bar",
            data: {
                labels: dias.map((d) => d.dia_corto),
                datasets: [
                    {
                        label: "Gasto",
                        data: dias.map((d) => d.importe),
                        backgroundColor: dias.map((d) =>
                            d.importe === mayor ? PALETA.principal : alfa(PALETA.principal, "77")
                        ),
                        borderRadius: RADIO_BARRA,
                        maxBarThickness: 40,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (c) =>
                                " " +
                                formatoMoneda(c.parsed.y) +
                                "  ·  " +
                                dias[c.dataIndex].tickets +
                                " tickets",
                            title: (items) => dias[items[0].dataIndex].dia,
                        },
                    },
                },
                scales: {
                    x: { grid: { display: false }, border: { display: false } },
                    y: ejeDinero,
                },
            },
        });
    }

    function dibujar(d) {
        PALETA = paleta();
        estiloGeneral();
        const jobs = [
            ["g-mes", d.meses, graficaPeriodo],
            ["g-categoria", d.categorias, graficaCategoria],
            ["g-subcategoria", d.subcategorias, graficaSubcategoria],
            ["g-dia", d.dias_semana, graficaDiaSemana],
        ];
        for (const [id, datos, fn] of jobs) {
            if (Array.isArray(datos) && datos.length) fn(datos);
            else avisar(id, "Sin datos para esta gráfica.");
        }
    }

    // Un fallo al pedir los datos es la causa número uno de un panel en blanco,
    // así que se reporta en consola y en la tarjeta, no se traga en silencio.
    const periodo = document.getElementById("sel-periodo");
    const url =
        "/panel/datos" + (periodo && periodo.value ? "?periodo=" + periodo.value : "");

    fetch(url)
        .then((r) => {
            if (!r.ok) throw new Error("HTTP " + r.status);
            return r.json();
        })
        .then((d) => {
            dibujar(d);
            // Al cambiar de tema se redibuja con los mismos datos.
            document.addEventListener("tema-cambiado", () => {
                graficas.splice(0).forEach((g) => g.destroy());
                dibujar(d);
            });
        })
        .catch((e) => {
            console.error("panel: no se pudieron cargar los datos", e);
            ["g-mes", "g-categoria", "g-subcategoria", "g-dia"].forEach((id) =>
                avisar(id, "No se pudieron cargar los datos del panel.")
            );
        });
})();
