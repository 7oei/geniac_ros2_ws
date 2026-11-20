"""Private SSH transfer from mother; k5 verifies videos before public registration."""
import argparse
import fcntl
import json
import os
import re
import signal
import subprocess
import threading
import time
from pathlib import Path
from .archive_queue import ArchiveQueue
from .bag_archive import digest
from .screen_video import atomic_json,video_info
from .scenario_audio import mux_audio

ID=re.compile(r'screen_[0-9]{8}T[0-9]{6}Z_[a-f0-9]{32}')


def import_video(root,name):
    if not ID.fullmatch(name):raise ValueError('Invalid video ID')
    q=ArchiveQueue(root);incoming=q.root/'video_incoming';directory=q.root/'archives';directory.mkdir(exist_ok=True)
    if incoming.is_symlink() or directory.is_symlink():raise ValueError('Invalid video directories')
    manifest=incoming/(name+'.json.pending');source=incoming/(name+'.mp4.pending')
    if manifest.is_symlink() or source.is_symlink():raise ValueError('Invalid incoming file')
    data=json.loads(manifest.read_text())
    if data['id']!=name or not re.fullmatch('[a-f0-9]{64}',data['sha256']):raise ValueError('Invalid video manifest')
    with q.connect() as c:old=c.execute('SELECT * FROM jobs WHERE name=?',(name,)).fetchone()
    if old:
        source_hash=json.loads(old['story']).get('screen_source_sha256',old['sha256'])
        if source_hash!=data['sha256']:raise ValueError('Video ID conflict')
        if source.exists():source.unlink()
        return {'id':name,'sha256':data['sha256'],'size':data['size'],'stored':True,'audio':json.loads(old['story']).get('screen_audio','unavailable')}
    if source.stat().st_size!=data['size'] or digest(source)!=data['sha256']:
        raise ValueError('Video checksum mismatch')
    info=video_info(source)
    muxed=incoming/(name+'.mux.mp4')
    if muxed.is_symlink():raise ValueError('Invalid mux output')
    selected,audio_status=mux_audio(q.root,data,source,muxed)
    final_sha=digest(selected);final_size=selected.stat().st_size
    target=directory/(name+'_'+final_sha[:16]+'.mp4')
    if target.is_symlink():raise ValueError('Invalid video target')
    # Keep the uploaded source until the receipt is committed, so interrupted mux/import retries are safe.
    if selected==source:
        import shutil
        shutil.copyfile(source,target)
    else:selected.replace(target)
    with target.open('rb') as f:os.fsync(f.fileno())
    story=dict(data['story']);story.update(screen_episode=data.get('episode',''),screen_duration=float(info['format']['duration']),
                                         screen_source_sha256=data['sha256'],screen_audio=audio_status)
    with q.connect() as c:
        c.execute('''INSERT OR IGNORE INTO jobs(name,created,story,state,outcome,archive,sha256,size,kind)
                     VALUES(?,?,?,?,?,?,?,?,?)''',(name,float(data['created']),json.dumps(story,ensure_ascii=False),'compressed',
                     str(data['outcome']),target.name,final_sha,final_size,'video'))
    source.unlink()
    return {'id':name,'sha256':data['sha256'],'size':data['size'],'stored':True,'audio':audio_status}


def import_main():
    parser=argparse.ArgumentParser();parser.add_argument('id');parser.add_argument('--root',default=str(Path.home()/'geniac_bags'))
    args=parser.parse_args();print(json.dumps(import_video(args.root,args.id)))


class Transfer:
    def __init__(self,root,target,run=subprocess.run,limit=100_000_000_000):
        self.root=Path(root).expanduser();self.root.mkdir(parents=True,exist_ok=True)
        if not re.fullmatch(r'[a-zA-Z0-9_-]+@[a-zA-Z0-9.-]+',target):raise ValueError('Invalid SSH target')
        self.target=target;self.run=run;self.limit=limit
        self.remote='/home/air-water/geniac_bags/video_incoming/'
    def command(self,args,timeout=3600):
        return self.run(args,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)
    def step(self):
        for path in sorted(self.root.glob('screen_*.json')):
            if path.name.endswith(('.error.json','.upload.json')):continue
            try:
                data=json.loads(path.read_text())
                if data.get('status')=='transferred' or data.get('retry_at',0)>time.time():continue
                name=data['id']
                if not ID.fullmatch(name) or data['filename']!=name+'.mp4':raise ValueError('Invalid local video')
                video=self.root/data['filename']
                if video.is_symlink():raise ValueError('Invalid local video')
                data.update(sha256=digest(video),size=video.stat().st_size)
                descriptor=self.root/(name+'.upload.json');atomic_json(descriptor,data)
                ssh=['ssh','-o','BatchMode=yes','-o','ConnectTimeout=5',self.target]
                self.command(ssh+['mkdir -p '+self.remote],timeout=15)
                for source,suffix in [(video,'.mp4.pending'),(descriptor,'.json.pending')]:
                    self.command(['rsync','--partial','--bwlimit=2000','-e','ssh -o BatchMode=yes -o ConnectTimeout=5',str(source),self.target+':'+self.remote+name+suffix])
                result=self.command(ssh+['/home/air-water/geniac_ros2_ws/scripts/geniac-video-import '+name],timeout=120)
                receipt=json.loads(result.stdout)
                if not receipt.get('stored') or receipt.get('sha256')!=data['sha256'] or receipt.get('size')!=data['size']:
                    raise ValueError('Remote video receipt mismatch')
                data.update(status='transferred',error='',retry_at=0);atomic_json(path,data)
            except Exception as exc:
                try:
                    data=json.loads(path.read_text());data.update(error=type(exc).__name__,retry_at=time.time()+15);atomic_json(path,data)
                except Exception:pass
            break
        self.prune()
    def prune(self):
        total=sum(p.stat().st_size for p in self.root.glob('screen_*.mp4') if p.is_file() and not p.is_symlink())
        entries=[]
        for p in self.root.glob('screen_*.json'):
            if p.name.endswith(('.error.json','.upload.json')):continue
            try:
                d=json.loads(p.read_text())
                if d.get('status')=='transferred' and ID.fullmatch(d['id']) and d.get('filename')==d['id']+'.mp4':entries.append((d['created'],p,d))
            except (ValueError,KeyError):continue
        for _,p,d in sorted(entries):
            if total<=self.limit:break
            video=self.root/d['filename']
            if video.is_file() and not video.is_symlink():total-=video.stat().st_size;video.unlink()
            d['local_pruned']=True;atomic_json(p,d)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',default=str(Path.home()/'geniac_screen_recordings'))
    parser.add_argument('--target',default='air-water@192.168.1.64');args=parser.parse_args()
    transfer=Transfer(args.root,args.target)
    lock=(transfer.root/'transfer.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    closed=threading.Event();signal.signal(signal.SIGTERM,lambda *_:closed.set());signal.signal(signal.SIGINT,lambda *_:closed.set())
    while not closed.is_set():transfer.step();closed.wait(2)
