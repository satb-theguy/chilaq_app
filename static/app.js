// static/app.js
(function () {
  function $(sel, root) { return (root || document).querySelector(sel); }
  function $all(sel, root) { return Array.from((root || document).querySelectorAll(sel)); }

  function refreshLikeCounts() {
    $all("[data-like-count]").forEach(function(el) {
      const pid = el.getAttribute("data-like-count");
      fetch(`/posts/${pid}/likes`, { credentials: "same-origin" })
        .then(r => r.ok ? r.json() : null)
        .then(data => { if (data && typeof data.likes === "number") el.textContent = data.likes; })
        .catch(() => {});
    });
  }

  function bindLikeButtons() {
    $all("[data-like-btn]").forEach(function(btn) {
      btn.addEventListener("click", function(e) {
        e.preventDefault();
        const pid = btn.getAttribute("data-like-btn");
        fetch(`/api/posts/${pid}/like`, { method: "POST", credentials: "same-origin" })
          .then(r => r.ok ? r.json() : null)
          .then(data => {
            if (!data) return;
            const target = document.querySelector(`[data-like-count="${pid}"]`);
            if (target && typeof data.likes === "number") target.textContent = data.likes;
          })
          .catch(() => {});
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function() {
    refreshLikeCounts();
    bindLikeButtons();
  });
})();