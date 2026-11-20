"""Durable episode archive queue and Discord outbox shared by recorder and worker."""
import json
from contextlib import contextmanager
import re
import sqlite3
import time
from pathlib import Path


class ArchiveQueue:
    def __init__(self,root):
        self.root=Path(root).expanduser().resolve()
        self.directory=self.root/'.archive';self.directory.mkdir(parents=True,exist_ok=True)
        self.directory.chmod(0o700)
        self.db=self.directory/'queue.sqlite3'
        with self.connect() as c:
            c.executescript('''
              CREATE TABLE IF NOT EXISTS jobs (
                name TEXT PRIMARY KEY, created REAL NOT NULL, story TEXT NOT NULL,
                state TEXT NOT NULL, outcome TEXT DEFAULT '', archive TEXT DEFAULT '',
                sha256 TEXT DEFAULT '', inventory TEXT DEFAULT '', size INTEGER DEFAULT 0,
                remote TEXT DEFAULT '', attempts INTEGER DEFAULT 0, retry_at REAL DEFAULT 0,
                error TEXT DEFAULT '', pruned INTEGER DEFAULT 0);
              CREATE TABLE IF NOT EXISTS outbox (
                id TEXT PRIMARY KEY, text TEXT NOT NULL, created REAL NOT NULL,
                sent INTEGER DEFAULT 0, attempts INTEGER DEFAULT 0, retry_at REAL DEFAULT 0);
            ''')
    @contextmanager
    def connect(self):
        c=sqlite3.connect(self.db,timeout=10);c.row_factory=sqlite3.Row
        try:
            with c:yield c
        finally:c.close()
    def bag(self,name):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,180}',name):raise ValueError('Invalid bag name')
        path=self.root/name
        if path.is_symlink() or path.resolve().parent!=self.root:raise ValueError('Bag outside recording directory')
        return path
    def started(self,path,story):
        path=Path(path)
        if path.parent.resolve()!=self.root:raise ValueError('Bag outside recording directory')
        self.bag(path.name)
        now=time.time();title=str(story.get('title',''))[:400];number=story.get('sequence','—')
        with self.connect() as c:
            c.execute('INSERT OR IGNORE INTO jobs(name,created,story,state) VALUES(?,?,?,?)',
                      (path.name,now,json.dumps(story,ensure_ascii=False),'recording'))
            c.execute('INSERT OR IGNORE INTO outbox(id,text,created) VALUES(?,?,?)',
                      (path.name+':start',f'GENIAC: シナリオ No.{number}「{title}」の再生を開始しました。\n完全退避まで録画します。\n記録ID: {path.name}',now))
    def finished(self,path,outcome,success=True):
        with self.connect() as c:
            c.execute("UPDATE jobs SET state=?,outcome=?,error=? WHERE name=? AND state='recording'",
                      ('queued' if success else 'recording_error',outcome,'' if success else 'Recording did not close cleanly',Path(path).name))
    def update(self,name,**fields):
        allowed={'state','archive','sha256','inventory','size','remote','attempts','retry_at','error','pruned','outcome'}
        if not fields or not set(fields)<=allowed:raise ValueError('Invalid queue fields')
        with self.connect() as c:
            c.execute('UPDATE jobs SET '+','.join(k+'=?' for k in fields)+' WHERE name=?',(*fields.values(),name))
    def rows(self):
        with self.connect() as c:return [dict(r) for r in c.execute('SELECT * FROM jobs ORDER BY created,name')]
    def published(self,name,receipt):
        with self.connect() as c:
            c.execute("UPDATE jobs SET state='published',remote=?,error='',retry_at=0 WHERE name=?",(json.dumps(receipt),name))
    def completed(self,name):
        with self.connect() as c:
            row=c.execute('SELECT * FROM jobs WHERE name=?',(name,)).fetchone()
            receipt=json.loads(row['remote']);story=json.loads(row['story'])
            text=(f"GENIAC: シナリオ No.{story.get('sequence','—')} のROSBAGの圧縮とダウンロード準備が完了しました。\n"
                  f"終了理由: {row['outcome']}\nファイル: {row['archive']}\n保存先: {receipt['url']}")
            c.execute("UPDATE jobs SET state='done',error='' WHERE name=?",(name,))
            c.execute('INSERT OR IGNORE INTO outbox(id,text,created) VALUES(?,?,?)',(name+':ready',text,time.time()))
    def notify_once(self,webhook,send):
        if not webhook:return
        with self.connect() as c:
            rows=c.execute('SELECT * FROM outbox WHERE sent=0 AND retry_at<=? ORDER BY created LIMIT 10',(time.time(),)).fetchall()
        for row in rows:
            try:ok=send(webhook,row['text'])
            except Exception:ok=False  # Never log transport exceptions containing credentials.
            attempts=row['attempts']+1
            with self.connect() as c:
                c.execute('UPDATE outbox SET sent=?,attempts=?,retry_at=? WHERE id=?',
                          (int(ok),attempts,time.time()+min(300,5*2**min(attempts,6)),row['id']))
