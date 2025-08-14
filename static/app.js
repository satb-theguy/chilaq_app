// === like UI（index/post 共通・これ1本に統一） ===

// Cookieの値を取得（liked_{id} を見る）
function getCookie(name){
  const m = document.cookie.match('(?:^|; )' + name.replace(/([.$?*|{}()[\]\\/+^])/g, '\\$1') + '=([^;]*)');
  return m ? decodeURIComponent(m[1]) : undefined;
}

// ボタンの見た目を切り替え（ピンク/グレー）
function setLikedClass(postId, liked){
  const btn = document.getElementById(`like-btn-${postId}`);
  if(!btn) return;
  btn.classList.toggle('liked', !!liked);
}

// DBの最新いいね数で上書き（初期表示/リロード用）
async function refreshLikeCount(postId){
  try{
    const res = await fetch(`/posts/${postId}/likes`, { cache: 'no-store' });
    if(!res.ok) return;
    const data = await res.json(); // {post_id, likes}
    const el = document.getElementById(`like-count-${postId}`);
    if(el) el.textContent = data.likes;
    setLikedClass(postId, getCookie(`liked_${postId}`) === '1');
  }catch(_e){ /* no-op */ }
}

// クリック時にHTMLの onclick から呼ばれるグローバル関数
window.likePost = async function(postId){
  const btn = document.getElementById(`like-btn-${postId}`);
  const countEl = document.getElementById(`like-count-${postId}`);
  const already = getCookie(`liked_${postId}`) === '1';

  // 既に♥済みなら色合わせだけして終わり
  if (already) { setLikedClass(postId, true); return; }

  // 現在表示の数を保持
  const prev = countEl ? parseInt(countEl.textContent || '0', 10) || 0 : 0;

  // 楽観的更新（先にUIを増やす）
  if (countEl) countEl.textContent = prev + 1;
  setLikedClass(postId, true);
  if (btn) btn.disabled = true;

  try{
    const res = await fetch(`/posts/${postId}/like`, {
      method: 'POST',
      headers: { 'Accept': 'application/json' }
    });
    if(!res.ok) throw new Error(`bad status ${res.status}`);
    const data = await res.json(); // {likes, liked:true}
    if (countEl && typeof data.likes === 'number') {
      countEl.textContent = data.likes; // サーバ値で確定
    }
  }catch(err){
    // 失敗ならロールバック
    if (countEl) countEl.textContent = prev;
    setLikedClass(postId, false);
    console.warn('like failed:', err);
    alert('いいねに失敗しました');
  }finally{
    if (btn) btn.disabled = false;
  }
};

// 初期化：ページ内の全postの最新値で上書き＆色合わせ
document.addEventListener('DOMContentLoaded', () => {
  const ids = Array.from(document.querySelectorAll('.like-count'))
    .map(el => {
      const m = el.id && el.id.match(/^like-count-(\d+)$/);
      return m ? Number(m[1]) : null;
    })
    .filter(Boolean);
  ids.forEach(id => refreshLikeCount(id));
});