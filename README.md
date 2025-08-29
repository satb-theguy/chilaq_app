# Chilaq — 音楽ディグSNS (MVP)

## 起動

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
# http://127.0.0.1:8000
```

## できること
- 一般閲覧（ホーム/アーティスト/投稿詳細、♥）
- 管理者：アーティスト作成・ユーザーへの紐付け、任意アーティストとして代理投稿、全投稿の削除
- アーティスト：自分の投稿一覧、新規投稿、削除（自分のアーティスト分のみ）

## 重要
- パスワードハッシュは**簡易**です。運用時は `passlib[bcrypt]` などに置き換えてください。
- SQLite はローカル専用。Render では `DATABASE_URL` を Postgres の接続文字列にして使います。
