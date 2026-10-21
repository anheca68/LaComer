/**
 * Toggle para mostrar/ocultar secciones de tickets.
 * Guarda la preferencia en localStorage para persistir entre sesiones.
 */
(function () {
    'use strict';

    const PREFIJO_KEY = 'toggle_';

    function initToggle(btn) {
        const targetId = btn.getAttribute('data-target');
        const contenido = document.getElementById(targetId);
        if (!contenido) return;

        // Restaurar preferencia guardada
        const key = PREFIJO_KEY + targetId;
        const guardado = localStorage.getItem(key);
        if (guardado === 'oculto') {
            contenido.style.display = 'none';
            btn.textContent = '▶';
            btn.setAttribute('aria-expanded', 'false');
        }

        btn.addEventListener('click', function () {
            const oculto = contenido.style.display === 'none';
            if (oculto) {
                contenido.style.display = '';
                btn.textContent = '▼';
                btn.setAttribute('aria-expanded', 'true');
                localStorage.setItem(key, 'visible');
            } else {
                contenido.style.display = 'none';
                btn.textContent = '▶';
                btn.setAttribute('aria-expanded', 'false');
                localStorage.setItem(key, 'oculto');
            }
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        document.querySelectorAll('.btn-toggle').forEach(initToggle);
    });
})();
