// static/app.js
// いいね（likes）を “likes” に一本化。ローカル永続化は localStorage。

(function () {
  const KEY = (id) => `liked:${id}`;

  function hasLiked(id) {
    try { return localStorage.getItem(KEY(id)) === '1'; } catch { return false; }
  }
  function markLiked(id) {
    try { localStorage.setItem(KEY(id), '1'); } catch {}
  }

  function paint(btn, liked) {
    // .like-btn / .liked スタイルに依存（app.cssと一致）
    btn.classList.toggle('liked', liked);
    btn.setAttribute('aria-pressed', liked ? 'true' : 'false');
  }

  function updateSamePostButtons(id, liked, count) {
    document.querySelectorAll(`.like-btn[data-post-id="${id}"]`).forEach((el) => {
      paint(el, liked);
      if (typeof count === 'number') {
        const span = el.querySelector('.count');
        if (span) span.textContent = count;
      }
    });
  }

  async function fetchLikes(id) {
    try {
      const res = await fetch(`/posts/${id}/likes`, { cache: 'no-store', headers: { 'Accept': 'application/json' } });
      if (!res.ok) return null;
      const json = await res.json(); // {post_id, likes}
      return typeof json?.likes === 'number' ? json.likes : null;
    } catch {
      return null;
    }
  }

  async function postLike(id) {
    // 互換のため両方試す（どちらも likes を返す想定）
    const candidates = [`/api/posts/${id}/like`, `/p/${id}/like`];
    for (const url of candidates) {
      try {
        const res = await fetch(url, { method: 'POST', headers: { 'Accept': 'application/json' } });
        if (res.ok) {
          const json = await res.json(); // {liked:true, likes:<int>}
          if (json && typeof json.likes === 'number') return json.likes;
          return null;
        }
      } catch { /* next */ }
    }
    return null;
  }

  async function initHearts() {
    // 初期マーキング
    document.querySelectorAll('.like-btn[data-post-id]').forEach((btn) => {
      const id = btn.getAttribute('data-post-id');
      paint(btn, hasLiked(id));
    });

    // 初期カウント同期（必要に応じて）
    const ids = Array.from(document.querySelectorAll('.like-btn[data-post-id]'))
      .map(el => Number(el.getAttribute('data-post-id')))
      .filter(Boolean);
    // 重複排除
    [...new Set(ids)].forEach(async (id) => {
      const likes = await fetchLikes(id);
      if (likes !== null) updateSamePostButtons(id, hasLiked(id), likes);
    });

    // クリック
    document.addEventListener('click', async (e) => {
      const btn = e.target.closest('.like-btn[data-post-id]');
      if (!btn) return;

      const id = btn.getAttribute('data-post-id');
      if (hasLiked(id)) return; // 二重押下ガード

      // 楽観的更新
      const countEl = btn.querySelector('.count');
      const current = parseInt(countEl?.textContent || '0', 10) || 0;
      markLiked(id);
      updateSamePostButtons(id, true, current + 1);

      // サーバ反映
      const serverLikes = await postLike(id);
      if (typeof serverLikes === 'number') {
        updateSamePostButtons(id, true, serverLikes);
      } else {
        // 失敗時にロールバックしたいなら以下を有効化
        // localStorage.removeItem(KEY(id));
        // updateSamePostButtons(id, false, current);
        console.warn('like request failed or no likes returned');
      }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initHearts);
  } else {
    initHearts();
  }
})();