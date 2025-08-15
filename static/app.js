// static/app.js

// ---- localStorage helpers ----
const LIKE_KEY = (id) => `liked:${id}`;
function hasLiked(id) {
  try { return localStorage.getItem(LIKE_KEY(id)) === '1'; } catch { return false; }
}
function setLiked(id) {
  try { localStorage.setItem(LIKE_KEY(id), '1'); } catch {}
}

// ---- UI paint ----
function paintLike(btn, liked) {
  if (!btn) return;
  btn.classList.toggle('liked', !!liked);
  btn.setAttribute('aria-pressed', liked ? 'true' : 'false');
  // 押したら無効化したい場合は次を有効に： if (liked) btn.disabled = true;
}

// ---- 同一 post-id のボタン群を同期 ----
function updateSamePostButtons(id, liked, count) {
  document.querySelectorAll(`.like-btn[data-post-id="${id}"]`).forEach((el) => {
    paintLike(el, liked);
    const c = el.querySelector('.count');
    if (c && typeof count === 'number') c.textContent = String(count);
  });
}

// ---- API 呼び分け（後方互換。統一は Step 3 で） ----
async function postLikeToAny(endpoints) {
  for (const url of endpoints) {
    try {
      const res = await fetch(url, { method: 'POST', headers: { 'Accept': 'application/json' } });
      if (res.ok) { try { return await res.json(); } catch { return {}; } }
    } catch (_) { /* try next */ }
  }
  throw new Error('all like endpoints failed');
}

// ---- 初期化 ----
function initLikes() {
  document.querySelectorAll('.like-btn[data-post-id]').forEach((btn) => {
    const id = btn.getAttribute('data-post-id');
    paintLike(btn, hasLiked(id));

    btn.addEventListener('click', async (e) => {
      e.preventDefault();
      if (hasLiked(id)) return; // 連打ガード（UI側）

      // 候補エンドポイント（順に試す）
      let endpoints = [];
      const attr = btn.getAttribute('data-like-endpoints');
      if (attr) { try { endpoints = JSON.parse(attr); } catch {} }
      if (!endpoints.length) {
        endpoints = [`/p/${id}/like`, `/api/posts/${id}/like`, `/posts/${id}/like`];
      }

      const countEl = btn.querySelector('.count');
      const current = parseInt(countEl?.textContent || '0', 10) || 0;

      // 楽観的更新
      setLiked(id);
      updateSamePostButtons(id, true, current + 1);

      try {
        const json = await postLikeToAny(endpoints);
        if (typeof json?.likes === 'number') {
          updateSamePostButtons(id, true, json.likes);
        } else if (typeof json?.hearts === 'number') {
          // 旧レスポンス互換
          updateSamePostButtons(id, true, json.hearts);
        }
      } catch (err) {
        console.warn('like request failed:', err);
        // 必要ならロールバック：
        // localStorage.removeItem(LIKE_KEY(id));
        // updateSamePostButtons(id, false, current);
      }
    });
  });
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initLikes);
} else {
  initLikes();
}