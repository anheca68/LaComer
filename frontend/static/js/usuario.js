/* ============================================================
   usuario.js — Menú del avatar (Settings y Cerrar sesión)
   ============================================================ */

(function () {
    const boton = document.getElementById("avatar-usuario");
    const panel = document.getElementById("menu-usuario");
    if (!boton || !panel) return;  // Sin sesión (pantalla de login)

    function abrir() {
        panel.hidden = false;
        boton.setAttribute("aria-expanded", "true");
        const primero = panel.querySelector("[role=menuitem]");
        if (primero) primero.focus();
    }

    function cerrar(devolverFoco) {
        panel.hidden = true;
        boton.setAttribute("aria-expanded", "false");
        if (devolverFoco) boton.focus();
    }

    boton.addEventListener("click", function () {
        if (panel.hidden) abrir();
        else cerrar(false);
    });

    // Clic fuera del menú lo cierra.
    document.addEventListener("click", function (evento) {
        if (!panel.hidden && !evento.target.closest(".menu-usuario")) cerrar(false);
    });

    // Escape cierra; flechas recorren las opciones.
    document.addEventListener("keydown", function (evento) {
        if (panel.hidden) return;
        if (evento.key === "Escape") {
            cerrar(true);
            return;
        }
        if (evento.key !== "ArrowDown" && evento.key !== "ArrowUp") return;
        const opciones = Array.from(panel.querySelectorAll("[role=menuitem]"));
        const actual = opciones.indexOf(document.activeElement);
        const paso = evento.key === "ArrowDown" ? 1 : -1;
        opciones[(actual + paso + opciones.length) % opciones.length].focus();
        evento.preventDefault();
    });
})();
