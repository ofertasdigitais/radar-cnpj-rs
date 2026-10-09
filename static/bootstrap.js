document.documentElement.dataset.theme = localStorage.getItem("radar-theme") || "dark";

document.addEventListener("DOMContentLoaded", () => {
  document.body.dataset.view = location.hash.slice(1) || "dashboard";
});
