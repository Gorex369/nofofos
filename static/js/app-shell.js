(function () {
    var toggle = document.querySelector("[data-nav-toggle]");
    var sidebar = document.querySelector("[data-sidebar]");
    if (!toggle || !sidebar) return;
    toggle.addEventListener("click", function () {
        var open = sidebar.classList.toggle("is-open");
        toggle.setAttribute("aria-expanded", String(open));
    });
}());
