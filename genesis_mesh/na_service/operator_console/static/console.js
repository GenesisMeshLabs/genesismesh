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

    function initPagination() {
        document.querySelectorAll("[data-paginate]").forEach(function (table) {
            // Tables paginate their body rows; other containers their own children.
            var body = table.querySelector("tbody") || table;
            var items = body === table
                ? Array.from(body.children)
                : Array.from(body.querySelectorAll("tr"));
            var rows = items.filter(function (row) {
                return !row.classList.contains("empty-row");
            });
            var size = parseInt(table.getAttribute("data-paginate"), 10) || 10;
            if (rows.length <= size) {
                return;
            }

            var pages = Math.ceil(rows.length / size);
            var current = 1;

            var controls = document.createElement("div");
            controls.className = "table-pager";
            var previous = document.createElement("button");
            previous.type = "button";
            previous.className = "filter-link";
            previous.textContent = "Previous";
            var next = document.createElement("button");
            next.type = "button";
            next.className = "filter-link";
            next.textContent = "Next";
            var status = document.createElement("span");
            status.className = "filter-summary";
            status.setAttribute("aria-live", "polite");
            controls.appendChild(previous);
            controls.appendChild(status);
            controls.appendChild(next);

            var anchor = table.closest(".table-wrap") || table;
            anchor.parentNode.insertBefore(controls, anchor.nextSibling);

            function show(page) {
                current = Math.min(Math.max(page, 1), pages);
                rows.forEach(function (row, index) {
                    var start = (current - 1) * size;
                    row.hidden = index < start || index >= start + size;
                });
                status.textContent = "Page " + current + " of " + pages + " · " + rows.length + " rows";
                previous.disabled = current === 1;
                next.disabled = current === pages;
            }

            previous.addEventListener("click", function () {
                show(current - 1);
            });
            next.addEventListener("click", function () {
                show(current + 1);
            });
            show(1);
        });
    }

    document.addEventListener("DOMContentLoaded", function () {
        initTheme();
        initSearch();
        initSurfaceFilters();
        initPagination();
        initBackToTop();
    });
})();
