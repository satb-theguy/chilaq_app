from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import logging, time, os

from app.db import engine
from app.models import Base
from app.routers import notes as notes_router
from app.routers import auth as auth_router
from app.routers import compare as compare_router

app = FastAPI(title="chilaq API")

# --- CORS ---
_raw = os.environ.get("ALLOW_ORIGINS", "")
ALLOWED_ORIGINS = [o.strip() for o in _raw.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS or [],
    allow_methods=["GET","POST","PUT","PATCH","DELETE","OPTIONS"],
    allow_headers=["*"],
    allow_credentials=True,
)

# --- Security headers ---
@app.middleware("http")
async def security_headers(request, call_next):
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    resp.headers["Strict-Transport-Security"] = "max-age=15552000; includeSubDomains; preload"
    return resp

# --- Logging ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("chilaq")

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    resp = await call_next(request)
    ms = (time.time() - start) * 1000
    logger.info(f'{request.method} {request.url.path} {resp.status_code} {ms:.1f}ms ip="{request.client.host}"')
    return resp

# --- Error handlers ---
@app.exception_handler(HTTPException)
async def http_exc_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code,
                        content={"error": exc.detail, "status_code": exc.status_code, "path": request.url.path})

@app.exception_handler(Exception)
async def unhandled_exc_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error")
    return JSONResponse(status_code=500, content={"error":"internal_error","message":"Something went wrong."})

# --- DB: テーブル作成（初回用）
@app.on_event("startup")
def on_startup():
    if engine:
        Base.metadata.create_all(engine)
        logger.info("tables ensured")
    else:
        logger.warning("DATABASE_URL not set")

# --- Basic routes ---
@app.get("/health")
def health():
    return {"status": "healthy"}

@app.get("/", response_class=HTMLResponse)
def index():
    return """
<!doctype html><meta charset="utf-8">
<title>自由比較テーブル</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  :root{
    --bg:#0B1020; --panel:#0F162D; --panel-2:#141C37;
    --border:#D9DFEC; --text:#E9EDF8; --muted:#9AA6CE;
    --primary:#6EA8FF; --primary-ink:#0B1020;
    --primary-soft: color-mix(in oklab, var(--primary) 72%, white 28%);
    --sorted:#0E2248; --shadow:0 2px 8px rgba(10,14,32,.06); --radius:14px;
    --danger:#ef4444;
  }
  @media (prefers-color-scheme: light){
    :root{
      --bg:#F6F7FB; --panel:#FFFFFF; --panel-2:#F9FAFE; --border:#DDE3F2;
      --text:#0C1226; --muted:#5D6A8C; --primary:#2563EB; --primary-ink:#fff;
      --primary-soft: color-mix(in oklab, var(--primary) 65%, white 35%);
      --sorted:#EEF2FF; --shadow:0 3px 10px rgba(13,31,69,.06);
      --danger:#dc2626;
    }
  }

  *,*::before,*::after{ box-sizing:border-box }

  html,body{height:100%}
  body{margin:0;font-family:ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial;background:var(--bg);color:var(--text)}
  .container{max-width:1040px;margin:28px auto;padding:0 16px}
  h1{margin:0 0 6px;font-size:28px}
  .lead{color:var(--muted);margin:0 0 16px}

  .card{background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);box-shadow:var(--shadow);padding:14px;margin-bottom:16px}
  .toolbar{display:grid;grid-template-columns:1.6fr 1fr auto;gap:12px}
  .group{display:flex;gap:8px;align-items:center;background:var(--panel-2);border:1px solid var(--border);border-radius:12px;padding:8px 10px;box-shadow:var(--shadow)}
  .label{color:var(--muted);font-size:12px}

  input,button,select{border-radius:12px;border:1px solid var(--border);background:transparent;color:var(--text)}
  input,select{padding:10px 12px}
  input{display:block;width:100%}
  input::placeholder{color:var(--muted)}
  button{padding:10px 14px;cursor:pointer;transition:all .15s ease}
  button.primary{background:var(--primary-soft);color:var(--primary-ink);border-color:transparent}
  #add-row{background:var(--primary-soft);color:var(--primary-ink);border-color:transparent}
  button.primary:hover,#add-row:hover{filter:brightness(1.04);transform:translateY(-1px)}
  button.ghost{background:transparent}
  button:focus-visible,input:focus-visible{outline:3px solid rgba(110,168,255,.35);outline-offset:1px}
  button[disabled]{opacity:.5;cursor:not-allowed;filter:none;transform:none}

  #header{ margin-bottom:8px }
  .header-row{
    display:grid !important;
    grid-template-columns: minmax(0,1.2fr) minmax(0,1.8fr) 42px;
    column-gap:12px; row-gap:0;
    align-items:end;
    padding-bottom:6px;
    border-bottom:1px solid var(--border);
  }
  .header-cell{position:relative;min-width:0;font-size:13px;color:var(--muted);letter-spacing:.2px;user-select:none;padding:10px 12px}
  .header-actions{width:42px;text-align:center;color:var(--muted);padding:10px 0}
  .header-cell.sorted{color:var(--text)}
  .header-cell .arrow{font-size:12px;margin-left:6px;opacity:.85}

  /* 編集モードのヘッダー上のコントロール */
  .edit-controls{
    position:absolute;left:50%;transform:translateX(-50%);
    top:-26px;display:flex;gap:6px;align-items:center;
  }
  .icon-btn{
    width:22px;height:22px;border:1px solid var(--border);border-radius:999px;
    display:inline-flex;align-items:center;justify-content:center;background:var(--panel-2);cursor:pointer
  }
  .icon-btn:hover{filter:brightness(1.04)}
  .icon-btn.danger{color:var(--danger);border-color:color-mix(in oklab, var(--danger) 50%, white 50%)}

  #rows{display:flex;flex-direction:column;gap:10px}
  .row-edit{
    display:grid !important;
    grid-template-columns: minmax(0,1.2fr) minmax(0,1.8fr) 42px;
    column-gap:12px; row-gap:0;
    align-items:center; width:100%;
  }
  .trash{
    width:42px; height:42px;
    display:inline-flex;align-items:center;justify-content:center;
    border-radius:12px;border:1px solid var(--border);
    background:transparent;color:var(--danger);
  }
  .trash:hover{background:rgba(239,68,68,.08)}
  .row-footer{display:flex;justify-content:center;margin-top:8px}

  .toast{position:fixed;bottom:18px;left:50%;transform:translateX(-50%);background:rgba(10,14,32,.92);color:#fff;padding:10px 14px;border-radius:999px;border:1px solid #2a3358}
  .toast button{margin-left:10px;background:#fff;color:#111;border:none;border-radius:999px;padding:6px 10px}
  .confirm{position:fixed;bottom:18px;left:50%;transform:translateX(-50%);display:flex;gap:10px;align-items:center;background:rgba(10,14,32,.92);color:#fff;padding:10px 14px;border-radius:999px;border:1px solid #2a3358}
  .confirm .ok{background:var(--danger);color:#fff;border:none;border-radius:999px;padding:6px 12px}
  .confirm .cancel{background:#fff;color:#111;border:none;border-radius:999px;padding:6px 12px}
</style>

<div class="container">
  <h1>自由比較テーブル</h1>
  <p class="lead">左から <b>名前 / URL</b> は固定。3列目以降は自由に追加できます。ヘッダクリックでソート。編集モードでは列の並び替え・名称変更・削除ができます。</p>

  <div class="card">
    <div class="toolbar">
      <div class="group" data-kind="cols">
        <span class="label">列</span>
        <input id="new-col" type="text" placeholder="新しい列名（例: 価格）" style="width:200px">
        <button id="add-col" type="button">＋ 列を追加</button>
        <button id="toggle-edit" type="button" class="primary">✏️ 列を編集</button>
      </div>
      <div class="group" data-kind="output">
        <span class="label">出力</span>
        <button id="copy" type="button">📄 表をコピー</button>
        <a id="dl" download="table.csv"><button type="button" class="ghost">⬇︎ CSV</button></a>
      </div>
      <div class="group" style="justify-self:end">
        <details>
          <summary style="cursor:pointer;color:var(--muted)">その他</summary>
          <div style="margin-top:8px">
            <button id="clear" type="button">🧹 全クリア</button>
          </div>
        </details>
      </div>
    </div>
  </div>

  <div class="card">
    <div id="header"></div>
    <div id="rows"></div>
    <div class="row-footer"><button id="add-row" type="button">➕ 行を追加</button></div>
  </div>
</div>

<script>
document.addEventListener('DOMContentLoaded', () => {
  const columns = ["名前","URL"];     // 左2列は固定（編集不可）
  let data = [{名前:"", URL:""}];
  let sortState = {key:null, dir:1};
  let lastSnapshot = null;
  let lastDeleted = null;
  let editMode = false;

  const headerEl = document.getElementById('header');
  const rowsBox  = document.getElementById('rows');
  const newColInput = document.getElementById('new-col');
  const addColBtn   = document.getElementById('add-col');
  const toggleEdit  = document.getElementById('toggle-edit');
  const addRowBtn   = document.getElementById('add-row');
  const copyBtn     = document.getElementById('copy');
  const dlLink      = document.getElementById('dl');
  const clearBtn    = document.getElementById('clear');

  const sanitizeCol = (s)=> s.replace(/\\s+/g,' ').trim();
  function detectNumber(x){ if(x==null) return null; const s=String(x).trim().replace(/[,\\s]/g,''); const n=Number(s); return isFinite(n)&&s!==""?n:null; }
  function isEmpty(v){ return v==null || String(v).trim()===""; }
  function toCSV(items, cols){
    const head = cols;
    const rows = items.map(row => cols.map(c => row[c] ?? ""));
    const quoteRe = new RegExp('"','g'); const needsRe = new RegExp('[",\\n]');
    const all = [head, ...rows];
    return all.map(r => r.map(v=>{ const s=String(v).replace(quoteRe,'""'); return needsRe.test(s)?`"${s}"`:s; }).join(",")).join("\\n");
  }
  const toast = (msg, undo=false, onUndo=null) => {
    const t=document.createElement('div'); t.className='toast'; t.textContent=msg;
    if(undo){ const b=document.createElement('button'); b.textContent='元に戻す'; b.onclick=()=>{onUndo&&onUndo(); document.body.removeChild(t)}; t.appendChild(b); }
    document.body.appendChild(t); setTimeout(()=>{ if(document.body.contains(t)) document.body.removeChild(t); }, 4000);
  };
  const confirmBar = (msg, onOk, onCancel) => {
    const el=document.createElement('div'); el.className='confirm';
    el.appendChild(Object.assign(document.createElement('span'),{textContent:msg}));
    const ok=Object.assign(document.createElement('button'),{className:'ok',textContent:'OK'});
    const cancel=Object.assign(document.createElement('button'),{className:'cancel',textContent:'キャンセル'});
    ok.onclick=()=>{document.body.removeChild(el); onOk&&onOk();};
    cancel.onclick=()=>{document.body.removeChild(el); onCancel&&onCancel();};
    el.appendChild(ok); el.appendChild(cancel); document.body.appendChild(el);
  };

  function buildColsTemplate(extra){
    return [
      'minmax(0, 1.2fr)',
      'minmax(0, 1.8fr)',
      ...Array(extra).fill('minmax(0, 1fr)'),
      '42px'
    ].join(' ');
  }

  // 空欄は常に末尾
  function sortData(){
    const key=sortState.key; if(!key) return;
    data.sort((a,b)=>{
      const av=a[key], bv=b[key];
      const aEmpty=isEmpty(av), bEmpty=isEmpty(bv);
      if(aEmpty && bEmpty) return 0;
      if(aEmpty && !bEmpty) return  1;
      if(!aEmpty && bEmpty) return -1;
      const an=detectNumber(av), bn=detectNumber(bv);
      let cmp=0;
      if(an!==null && bn!==null) cmp = an<bn?-1:an>bn?1:0;
      else { const as=String(av).toLowerCase(), bs=String(bv).toLowerCase(); cmp = as<bs?-1:as>bs?1:0; }
      return cmp * sortState.dir;
    });
  }

  function renameColumn(oldName, newName){
    const name = sanitizeCol(newName);
    if(!name || name===oldName) return false;
    if(columns.includes(name)) { alert("同名の列が既にあります"); return false; }
    const idx = columns.indexOf(oldName);
    if(idx<2) return false; // 固定列は不可
    columns[idx] = name;
    data.forEach(r => { r[name] = r[oldName]; delete r[oldName]; });
    return true;
  }

  function moveColumn(idx, dir){
    const newIdx = idx + dir;
    if(idx < 2) return;
    if(newIdx < 2 || newIdx > columns.length-1) return;
    const [col] = columns.splice(idx,1);
    columns.splice(newIdx,0,col);
  }

  function deleteColumn(idx){
    if(idx<2) return;
    const col = columns[idx];
    confirmBar(`列「${col}」を削除します。よろしいですか？`, () => {
      const removed = { idx, col, values: data.map(r => r[col]) };
      columns.splice(idx,1);
      data.forEach(r => delete r[col]);
      toast("列を削除しました", true, () => {
        columns.splice(removed.idx, 0, removed.col);
        data.forEach((r,i)=> r[removed.col] = removed.values[i]);
        fullRender();
      });
      fullRender();
    });
  }

  function renderHeaderRow(){
    const extra = Math.max(columns.length - 2, 0);
    headerEl.innerHTML = "";
    const wrap = document.createElement('div');
    wrap.className = 'header-row';
    wrap.style.setProperty('display','grid','important');
    wrap.style.setProperty('grid-template-columns', buildColsTemplate(extra), 'important');
    wrap.style.columnGap = '12px'; wrap.style.rowGap = '0px';
    wrap.style.alignItems = 'end'; wrap.style.paddingBottom = '6px';

    const makeCell = (label, key, idx) => {
      const c = document.createElement('div');
      c.className = 'header-cell';
      c.appendChild(document.createTextNode(label));  // ラベルだけを描画

      // 通常モード：ソート
      if (!editMode && key) {
        if (sortState.key === key) {
          const s = document.createElement('span'); s.className='arrow';
          s.textContent = sortState.dir===1 ? "▲" : "▼"; c.appendChild(s);
          c.classList.add('sorted');
        }
        c.style.cursor = "pointer";
        c.addEventListener('click', () => {
          if (sortState.key === key) sortState.dir *= -1; else { sortState.key=key; sortState.dir=1; }
          sortData(); fullRender();
        });
      }

      // 編集モード
      if (editMode) {
        // 名称編集（固定列は不可）
        if (idx>=2) {
          c.style.cursor = "text";
          c.addEventListener('click', () => {
            if (c.querySelector('input')) return;
            const current = columns[idx];        // ★ textContent ではなく列名を使う
            const input = document.createElement('input');
            input.type = 'text'; input.value = current; input.style.width = "100%";
            c.replaceChildren(input);            // 既存の矢印/−などを全置換
            input.focus(); input.select();
            const finish = () => {
              const ok = renameColumn(current, input.value);
              if(!ok){ c.replaceChildren(document.createTextNode(current)); }
              fullRender();
            };
            input.addEventListener('keydown', e => { if(e.key==="Enter") finish(); if(e.key==="Escape"){ c.replaceChildren(document.createTextNode(current)); }});
            input.addEventListener('blur', finish);
          });
        }

        // 上部コントロール（矢印＋削除）
        const canEdit = idx>=2;
        const ctr = document.createElement('div');
        ctr.className = 'edit-controls';

        if (canEdit && idx>2) {
          const left = document.createElement('div'); left.className='icon-btn'; left.title="左へ"; left.textContent="◀";
          left.onclick=(e)=>{ e.stopPropagation(); moveColumn(idx,-1); fullRender(); };   // ★ クリック伝播を止める
          ctr.appendChild(left);
        }
        if (canEdit && idx<columns.length-1) {
          const right = document.createElement('div'); right.className='icon-btn'; right.title="右へ"; right.textContent="▶";
          right.onclick=(e)=>{ e.stopPropagation(); moveColumn(idx,+1); fullRender(); };  // ★
          ctr.appendChild(right);
        }
        if (canEdit) {
          const del = document.createElement('div'); del.className='icon-btn danger'; del.title="列を削除"; del.textContent="—";
          del.style.marginLeft = "8px";
          del.onclick=(e)=>{ e.stopPropagation(); deleteColumn(idx); };                    // ★
          ctr.appendChild(del);
        }
        c.appendChild(ctr);
      }

      return c;
    };

    columns.forEach((col, idx) => {
      wrap.appendChild(makeCell(col, col, idx));
    });
    const act = document.createElement('div'); act.className='header-actions'; act.textContent=" ";
    wrap.appendChild(act);

    headerEl.appendChild(wrap);
  }

  function requestDeleteRow(index){
    confirmBar("この行を削除します。よろしいですか？", () => {
      const removed = data.splice(index,1)[0];
      lastDeleted = {row: removed, index};
      fullRender();
      toast("行を削除しました", true, () => {
        if(lastDeleted){ data.splice(lastDeleted.index,0,lastDeleted.row); lastDeleted=null; fullRender(); }
      });
    });
  }

  function renderEditors(){
    rowsBox.innerHTML = "";
    const extra = Math.max(columns.length - 2, 0);

    data.forEach((row, idx) => {
      const wrap = document.createElement('div');
      wrap.className = 'row-edit';
      wrap.style.setProperty('display','grid','important');
      wrap.style.setProperty('grid-template-columns', buildColsTemplate(extra), 'important');
      wrap.style.columnGap = '12px'; wrap.style.rowGap = '0px';
      wrap.style.alignItems = 'center'; wrap.style.width = '100%';

      // current columns 順に入力欄を生成
      const nameIn=document.createElement('input');
      nameIn.type="text"; nameIn.placeholder="名前"; nameIn.value=row["名前"]??"";
      nameIn.addEventListener('input', e=>{ row["名前"]=e.target.value; updateCSVLink(); });
      wrap.appendChild(nameIn);

      const urlIn=document.createElement('input');
      urlIn.type="text"; urlIn.placeholder="URL"; urlIn.value=row["URL"]??"";
      urlIn.addEventListener('input', e=>{ row["URL"]=e.target.value; updateCSVLink(); });
      wrap.appendChild(urlIn);

      for(let i=2;i<columns.length;i++){
        const key=columns[i];
        const inp=document.createElement('input');
        inp.type="text"; inp.placeholder=key; inp.value=row[key]??"";
        inp.addEventListener('input', e=>{ row[key]=e.target.value; updateCSVLink(); });
        wrap.appendChild(inp);
      }

      const delBtn=document.createElement('button');
      delBtn.type='button'; delBtn.className='trash'; delBtn.title='この行を削除';
      delBtn.innerHTML=`<svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
        <path d="M9 3h6a1 1 0 0 1 1 1v1h4v2h-1v12a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V7H4V5h4V4a1 1 0 0 1 1-1zm8 4H7v12h10V7zM9 9h2v8H9V9zm4 0h2v8h-2V9zM10 4v1h4V4h-4z"/>
      </svg>`;
      delBtn.addEventListener('click', () => requestDeleteRow(idx));
      delBtn.disabled = editMode;  // 編集モード中は削除不可
      wrap.appendChild(delBtn);

      rowsBox.appendChild(wrap);
    });
  }

  function updateCSVLink(){
    const csv = toCSV(data, columns);
    const blob = new Blob([csv], {type:'text/csv;charset=utf-8;'});
    dlLink.href = URL.createObjectURL(blob);
  }

  function fullRender(){
    if(!editMode) sortData();
    renderHeaderRow();
    renderEditors();
    updateCSVLink();
    addRowBtn.disabled = editMode;  // 編集モード中は行追加不可
  }

  addRowBtn.addEventListener('click', () => {
    const r={}; columns.forEach(c=> r[c] = "");
    data.push(r); fullRender();
  });

  addColBtn.addEventListener('click', () => {
    const raw=newColInput.value; const name=sanitizeCol(raw);
    if(!name){ alert("列名を入力してください"); return; }
    if(["名前","URL"].includes(name)){ alert("その列名は予約されています"); return; }
    if(columns.includes(name)){ alert("同じ列名が既にあります"); return; }
    columns.push(name);
    data.forEach(r=> r[name]=r[name]??"");
    newColInput.value="";
    sortState={key:name, dir:1};
    fullRender();
  });

  toggleEdit.addEventListener('click', () => {
    editMode = !editMode;
    toggleEdit.textContent = editMode ? "✅ 列の編集を完了" : "✏️ 列を編集";
    fullRender();
  });

  copyBtn.addEventListener('click', () => {
    const csv=toCSV(data, columns);
    navigator.clipboard.writeText(csv).then(()=> toast("CSVをコピーしました")).catch(()=> alert("コピーに失敗しました"));
  });

  function snapshot(){ lastSnapshot = JSON.parse(JSON.stringify({columns, data})); }
  function restore(){
    if(!lastSnapshot) return;
    columns.length=0; lastSnapshot.columns.forEach(c=>columns.push(c));
    data=lastSnapshot.data; lastSnapshot=null; fullRender();
  }
  clearBtn && clearBtn.addEventListener('click', () => {
    if(!confirm('本当にすべての入力を消去しますか？')) return;
    snapshot(); data=[{名前:"", URL:""}]; sortState={key:null,dir:1}; fullRender();
    toast('消去しました', true, restore);
  });

  fullRender();
});
</script>
"""

# --- Mount routers ---
app.include_router(notes_router.router)
app.include_router(auth_router.router)
app.include_router(compare_router.router)