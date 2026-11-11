/* ============================================================
   tema.js — Tema claro / oscuro
   ============================================================
   El tema se aplica antes de pintar con el script en línea de base.html;
   aquí solo se alterna con el botón de la barra superior y se guarda la
   elección. Al cambiar se emite el evento `tema-cambiado` para que las
   gráficas se vuelvan a dibujar con los colores del tema nuevo. */

(function () {
    "use strict";

    const raiz = document.documentElement;
    const boton = document.getElementById("cambiar-tema");

    function oscuro() {
        return raiz.getAttribute("data-tema") === "oscuro";
    }

    function aplicar(tema) {
        if (tema === "oscuro") raiz.setAttribute("data-tema", "oscuro");
        else raiz.removeAttribute("data-tema");
        try {
            localStorage.setItem("tema", tema);
        } catch (e) { /* localStorage puede estar bloqueado */ }
        if (boton) boton.setAttribute("aria-pressed", String(tema === "oscuro"));
        document.dispatchEvent(new CustomEvent("tema-cambiado", { detail: { tema } }));
    }

    if (boton) {
        boton.setAttribute("aria-pressed", String(oscuro()));
        boton.addEventListener("click", () => aplicar(oscuro() ? "claro" : "oscuro"));
    }

    // Colores de las gráficas leídos de las variables CSS del tema activo.
    window.colorTema = function (variable) {
        return getComputedStyle(raiz).getPropertyValue(variable).trim();
    };
})();
