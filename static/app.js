// --- localStorage で永続化（セッションが変わってもUIは維持） ---
function loadLiked() {
  try { return new Set(JSON.parse(localStorage.getItem('liked_posts') || '[]')); }
  catch { return new Set(); }
}
function saveLiked(set) {
  localStorage.setItem('liked_posts', JSON.stringify([...set]));
}
function markLikedButton(btn) {
  btn.classList.add('liked');
  btn.setAttribute('aria-pressed', 'true');
  btn.disabled = true;
}

document.addEventListener('DOMContentLoaded', () => {
  const liked = loadLiked();
  document.querySelectorAll('[data-like]').forEach(btn => {
    const id = Number(btn.getAttribute('data-like'));
    if (liked.has(id)) {
      markLikedButton(btn);
    }
  });
});

document.addEventListener('click', async (e) => {
  const btn = e.target.closest('[data-like]');
  if (!btn) return;

  const id = Number(btn.getAttribute('data-like'));
  if (btn.disabled || btn.classList.contains('liked')) return; // 二重送信防止
  btn.disabled = true;

  try {
    const res = await fetch(`/api/like/${id}`, { method: 'POST' });
    const json = await res.json();

    if (json.ok && json.liked) {
      const countEl = btn.querySelector('.count');
      if (countEl && typeof json.hearts === 'number') countEl.textContent = json.hearts;
      markLikedButton(btn);
      // 永続化
      const liked = loadLiked(); liked.add(id); saveLiked(liked);
    } else {
      // 既に♥済み or 連打 → UIだけ反映
      if (json.liked) {
        markLikedButton(btn);
        const liked = loadLiked(); liked.add(id); saveLiked(liked);
      } else if (json.reason === 'rate_limited') {
        // 軽いフィードバック
        btn.classList.add('btn-warning');
        setTimeout(() => btn.classList.remove('btn-warning'), 250);
        btn.disabled = false; // 少し待てば再度押せる
      } else {
        btn.disabled = false;
      }
    }
  } catch (err) {
    console.error(err);
    btn.disabled = false;
  }
});

// ---- Heart logic (共通) ----
(function () {
  const KEY = (id) => `liked:${id}`;

  function hasLiked(id) {
    try { return localStorage.getItem(KEY(id)) === '1'; } catch { return false; }
  }
  function markLiked(id) {
    try { localStorage.setItem(KEY(id), '1'); } catch {}
  }

  function paint(btn, liked) {
    btn.classList.toggle('heart-on', liked);
    btn.classList.toggle('heart-off', !liked);
  }

  async function postLike(endpoints) {
    // 複数候補を順に試す（/p/{id}/like → /api/posts/{id}/like）
    for (const url of endpoints) {
      try {
        const res = await fetch(url, { method: 'POST', headers: { 'Accept': 'application/json' } });
        if (res.ok) {
          try { return await res.json(); } catch { return {}; }
        }
      } catch (e) { /* next */ }
    }
    throw new Error('like failed');
  }

  function updateAllSamePost(id, liked, count) {
    // 同じ post-id を持つ全てのボタンの色・数を同期
    document.querySelectorAll(`.heart-btn[data-post-id="${id}"]`).forEach((el) => {
      paint(el, liked);
      if (typeof count === 'number') {
        const span = el.querySelector('.count');
        if (span) span.textContent = count;
      }
      // 既に liked 済みなら押下不可にしたい場合は以下を有効化：
      // el.disabled = liked;
    });
  }

  function initHearts() {
    document.querySelectorAll('.heart-btn[data-post-id]').forEach((btn) => {
      const id = btn.getAttribute('data-post-id');
      const liked = hasLiked(id);
      paint(btn, liked);
      // 既に liked 済みでも押せないようにするなら次を有効化
      // if (liked) btn.disabled = true;

      btn.addEventListener('click', async (e) => {
        e.preventDefault();
        if (hasLiked(id)) return; // 二重押下ガード（UI側）

        // エンドポイント候補を取得
        let endpoints = [];
        try { endpoints = JSON.parse(btn.getAttribute('data-like-endpoints') || '[]'); } catch {}
        if (!endpoints.length) {
          endpoints = [`/p/${id}/like`, `/api/posts/${id}/like`];
        }

        // カウント要素
        const countEl = btn.querySelector('.count');
        const current = parseInt(countEl?.textContent || '0', 10) || 0;

        // 楽観的更新（即時UI反映）
        markLiked(id);
        updateAllSamePost(id, true, current + 1);

        try {
          // サーバへ通知（成功/失敗問わず UI は維持。失敗時はロールバックしても良い）
          const json = await postLike(endpoints);
          if (typeof json?.hearts === 'number') {
            updateAllSamePost(id, true, json.hearts);
          }
        } catch {
          // 失敗時に戻したいなら以下を有効に
          // localStorage.removeItem(KEY(id));
          // updateAllSamePost(id, false, current);
          console.warn('like request failed');
        }
      });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initHearts);
  } else {
    initHearts();
  }
})();