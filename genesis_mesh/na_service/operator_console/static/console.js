(function () {
    function setTheme(theme) {
        var selected = theme === "light" ? "light" : "dark";
        document.documentElement.setAttribute("data-theme", selected);
        try {
            window.localStorage.setItem("genesis-mesh-theme", selected);
        } catch (_) {
            return;
        }
    }

    function initTheme() {
        var saved = "dark";
        try {
            saved = window.localStorage.getItem("genesis-mesh-theme") || "dark";
        } catch (_) {
            saved = "dark";
        }
        setTheme(saved);
        document.querySelectorAll("[data-theme-toggle]").forEach(function (button) {
            button.addEventListener("click", function () {
                var current = document.documentElement.getAttribute("data-theme") || "dark";
                setTheme(current === "dark" ? "light" : "dark");
            });
        });
    }

    function initSearch() {
        document.querySelectorAll("[data-search-input]").forEach(function (input) {
            var scopeSelector = input.getAttribute("data-search-scope");
            var targetSelector = input.getAttribute("data-search-target");
            var emptySelector = input.getAttribute("data-search-empty");
            var scope = scopeSelector ? document.querySelector(scopeSelector) : document;
            var empty = emptySelector ? document.querySelector(emptySelector) : null;
            if (!scope || !targetSelector) {
                return;
            }

            function applySearch() {
                var query = input.value.trim().toLowerCase();
                var visible = 0;
                scope.querySelectorAll(targetSelector).forEach(function (item) {
                    var matches = !query || item.textContent.toLowerCase().indexOf(query) !== -1;
                    item.classList.toggle("search-hidden", !matches);
                    if (matches) {
                        visible += 1;
                    }
                });
                scope.querySelectorAll("section").forEach(function (section) {
                    var items = Array.from(section.querySelectorAll(targetSelector));
                    if (!items.length) {
                        return;
                    }
                    var hasVisibleItem = items.some(function (item) {
                        return !item.classList.contains("search-hidden");
                    });
                    section.classList.toggle("search-hidden", !hasVisibleItem);
                });
                if (empty) {
                    empty.classList.toggle("search-empty-visible", visible === 0);
                }
            }

            input.addEventListener("input", applySearch);
            applySearch();
        });
    }

    function initSurfaceFilters() {
        var buttons = Array.from(document.querySelectorAll("[data-surface-filter]"));
        var sections = Array.from(document.querySelectorAll("[data-surface-section]"));
        if (!buttons.length || !sections.length) {
            return;
        }

        function applyFilter(filter) {
            buttons.forEach(function (button) {
                button.classList.toggle("filter-link-strong", button.getAttribute("data-surface-filter") === filter);
            });
            sections.forEach(function (section) {
                var category = section.getAttribute("data-surface-section");
                section.classList.toggle("surface-hidden", filter !== "all" && category !== filter);
            });
        }

        buttons.forEach(function (button) {
            button.addEventListener("click", function () {
                applyFilter(button.getAttribute("data-surface-filter") || "all");
            });
        });
        applyFilter("all");
    }

    function initBackToTop() {
        var button = document.querySelector("[data-back-to-top]");
        if (!button) {
            return;
        }

        function updateVisibility() {
            button.classList.toggle("back-to-top-visible", window.scrollY > 520);
        }

        button.addEventListener("click", function () {
            window.scrollTo({ top: 0, behavior: "smooth" });
        });
        window.addEventListener("scroll", updateVisibility, { passive: true });
        updateVisibility();
    }

    document.addEventListener("DOMContentLoaded", function () {
        initTheme();
        initSearch();
        initSurfaceFilters();
        initBackToTop();
    });
})();
