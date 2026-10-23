/* ============================================================
   menu.js — Barra lateral dinámica y tooltips
   ============================================================ */

(function () {
    const raiz = document.documentElement;
    const boton = document.getElementById("menu-toggle");
    const enlaces = document.querySelectorAll(".lateral nav a[data-tooltip]");
    const consultaMovil = window.matchMedia("(max-width: 1024px)");
    let temporizadorTooltip = null;

    function leerPreferencia(clave) {
        try {
            return localStorage.getItem(clave);
        } catch (e) {
            return null;
        }
    }

    function guardarPreferencia(clave, valor) {
        try {
            localStorage.setItem(clave, valor);
        } catch (e) {
            // Si el navegador bloquea localStorage, el menú sigue funcionando
            // durante la sesión actual.
        }
    }

    function limpiarTooltips() {
        clearTimeout(temporizadorTooltip);
        enlaces.forEach(function (enlace) {
            enlace.classList.remove("tooltip-visible");
        });
    }

    function menuExpandido() {
        if (consultaMovil.matches) {
            return raiz.classList.contains("menu-movil-expandido");
        }
        return !raiz.classList.contains("menu-colapsado");
    }

    function actualizarBoton() {
        if (!boton) return;
        const expandido = menuExpandido();
        boton.setAttribute("aria-expanded", String(expandido));
        boton.setAttribute(
            "aria-label",
            expandido ? "Contraer menú" : "Expandir menú"
        );
        boton.setAttribute(
            "title",
            expandido ? "Contraer menú" : "Expandir menú"
        );

        const icono = boton.querySelector(".menu-toggle-icono");
        const texto = boton.querySelector(".menu-toggle-texto");
        if (icono) icono.innerHTML = expandido ? "&#10094;" : "&#10095;";
        if (texto) texto.textContent = expandido ? "Ocultar" : "Mostrar";
    }

    function alternarMenu() {
        if (consultaMovil.matches) {
            const expandido = !raiz.classList.contains("menu-movil-expandido");
            raiz.classList.toggle("menu-movil-expandido", expandido);
            raiz.classList.remove("menu-colapsado");
            guardarPreferencia("menuMovilExpandido", expandido ? "1" : "0");
        } else {
            const colapsado = !raiz.classList.contains("menu-colapsado");
            raiz.classList.toggle("menu-colapsado", colapsado);
            raiz.classList.remove("menu-movil-expandido");
            guardarPreferencia("menuColapsado", colapsado ? "1" : "0");
        }

        limpiarTooltips();
        actualizarBoton();
    }

    if (boton) {
        boton.addEventListener("click", alternarMenu);
    }

    actualizarBoton();

    // Al cambiar de breakpoint cada tamaño recupera su propio estado:
    // escritorio expandido/colapsado y móvil iconos/etiquetas.
    function alCambiarBreakpoint(evento) {
        if (evento.matches) {
            raiz.classList.remove("menu-colapsado");
            raiz.classList.toggle(
                "menu-movil-expandido",
                leerPreferencia("menuMovilExpandido") === "1"
            );
        } else {
            raiz.classList.remove("menu-movil-expandido");
            raiz.classList.toggle(
                "menu-colapsado",
                leerPreferencia("menuColapsado") === "1"
            );
        }

        limpiarTooltips();
        actualizarBoton();
    }

    if (consultaMovil.addEventListener) {
        consultaMovil.addEventListener("change", alCambiarBreakpoint);
    } else if (consultaMovil.addListener) {
        consultaMovil.addListener(alCambiarBreakpoint);
    }

    function enModoIconos() {
        if (consultaMovil.matches) {
            return !raiz.classList.contains("menu-movil-expandido");
        }
        return raiz.classList.contains("menu-colapsado");
    }

    // Tooltips en pantallas táctiles: un toque sostenido sobre el icono
    // muestra su nombre. El toque normal sigue navegando.
    function mostrarTooltip(enlace) {
        if (!enModoIconos()) return;

        enlaces.forEach(function (otro) {
            otro.classList.remove("tooltip-visible");
        });
        enlace.classList.add("tooltip-visible");

        clearTimeout(temporizadorTooltip);
        temporizadorTooltip = setTimeout(function () {
            enlace.classList.remove("tooltip-visible");
        }, 1800);
    }

    enlaces.forEach(function (enlace) {
        enlace.addEventListener("touchstart", function () {
            mostrarTooltip(enlace);
        }, { passive: true });
    });
})();
