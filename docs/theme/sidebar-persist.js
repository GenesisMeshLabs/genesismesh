/*
 * Preserve sidebar scroll position across page navigations within a single
 * browsing session. Furo regenerates the sidebar on every page load (every
 * Sphinx page is a full HTML reload), so without this shim the sidebar feels
 * jumpy on navigation.
 *
 * Uses sessionStorage so the position resets when the tab is closed.
 */
(function () {
    "use strict";

    var STORAGE_KEY = "genesis-mesh-sidebar-scroll";

    function findSidebar() {
        return (
            document.querySelector(".sidebar-scroll") ||
            document.querySelector(".sidebar-tree")
        );
    }

    function restore(sidebar) {
        try {
            var saved = sessionStorage.getItem(STORAGE_KEY);
            if (saved !== null) {
                sidebar.scrollTop = parseInt(saved, 10) || 0;
            }
        } catch (e) {
            // sessionStorage may be unavailable in private browsing modes;
            // failing silently keeps the default Furo behaviour.
        }
    }

    function persistOnScroll(sidebar) {
        var ticking = false;
        sidebar.addEventListener("scroll", function () {
            if (ticking) return;
            ticking = true;
            window.requestAnimationFrame(function () {
                try {
                    sessionStorage.setItem(STORAGE_KEY, String(sidebar.scrollTop));
                } catch (e) {
                    // ignore
                }
                ticking = false;
            });
        });
    }

    function init() {
        var sidebar = findSidebar();
        if (!sidebar) return;
        restore(sidebar);
        persistOnScroll(sidebar);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
