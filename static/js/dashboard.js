document.querySelectorAll(".dashboard-progress").forEach(function (bar) {
    var percentage = Number.parseFloat(bar.dataset.progress);
    if (Number.isFinite(percentage)) {
        bar.style.width = Math.min(Math.max(percentage, 0), 100) + "%";
    }
});