/* ============================================================
   panel.js — Lógica del dashboard (gráficas, fetch de datos)
   ============================================================ */

(function () {
    "use strict";

    const PALETA = {
        azul: "#3d6ea5",
        gris: "#9aa8b7",
        rojo: "#c0392b",
        verde: "#27ae60",
    };

    // Recorta etiquetas largas: sin esto una descripción de 40 caracteres se
    // come el ancho del gráfico y empuja las barras fuera del área visible.
    const recortar = (valores, largo) =>
        valores.map((v) => {
            const t = String(v);
            return t.length > largo ? t.slice(0, largo - 1) + "…" : t;
        });

    const ejeDinero = {
        beginAtZero: true,
        ticks: {
            font: { size: 10 },
            callback: (v) => "$ " + v.toLocaleString("es-MX"),
        },
    };

    // Un canvas en blanco suele ser un canvas sin datos, no un canvas roto. Este
    // aviso en la tarjeta deja claro cuál de las dos cosas pasó.
    function avisar(id, texto) {
        const cv = document.getElementById(id);
        if (!cv) return;
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
            new window.Chart(cv, config);
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
                        backgroundColor: PALETA.gris,
                        borderRadius: 4,
                        order: 3,
                    },
                    {
                        label: "Neto",
                        data: serie.map((m) => m.neto),
                        backgroundColor: PALETA.azul,
                        borderRadius: 4,
                        order: 2,
                    },
                    {
                        label: "Descuentos",
                        data: serie.map((m) => m.descuentos),
                        type: "line",
                        borderColor: PALETA.rojo,
                        backgroundColor: PALETA.rojo,
                        borderWidth: 2,
                        pointRadius: 4,
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
                        position: "bottom",
                        labels: { boxWidth: 12, font: { size: 11 } },
                    },
                    tooltip: {
                        callbacks: {
                            label: (c) => " " + c.dataset.label + ": " + formatoMoneda(c.parsed.y),
                        },
                    },
                },
                scales: {
                    x: { grid: { display: false } },
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
                                ? PALETA.azul
                                : PALETA.azul + "99",
                        borderRadius: 4,
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
                        ticks: { font: { size: 10 }, autoSkip: false },
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
                        backgroundColor: PALETA.verde + "cc",
                        borderRadius: 4,
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
                    y: { grid: { display: false }, ticks: { font: { size: 10 } } },
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
                            d.importe === mayor ? PALETA.azul : PALETA.azul + "88"
                        ),
                        borderRadius: 4,
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
                    x: { grid: { display: false } },
                    y: ejeDinero,
                },
            },
        });
    }

    function dibujar(d) {
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
        .then(dibujar)
        .catch((e) => {
            console.error("panel: no se pudieron cargar los datos", e);
            ["g-mes", "g-categoria", "g-subcategoria", "g-dia"].forEach((id) =>
                avisar(id, "No se pudieron cargar los datos del panel.")
            );
        });
})();
