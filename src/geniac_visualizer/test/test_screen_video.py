import json
import shutil
import subprocess
import threading
import time
from types import SimpleNamespace as NS
import pytest
import requests
from geniac_visualizer.screen_video import VideoWriter,ScreenCapture,video_info,atomic_json
from geniac_visualizer.video_transfer import import_video,Transfer
from geniac_visualizer.archive_queue import ArchiveQueue
from geniac_visualizer.bag_archive import digest,Archiver
from geniac_visualizer.archive_server import DownloadServer


@pytest.fixture
def clip(tmp_path,monkeypatch):
    monkeypatch.setattr(VideoWriter,'width',160);monkeypatch.setattr(VideoWriter,'height',120)
    root=tmp_path/'mother'
    w=VideoWriter(root,{'epoch':'episode:1','story':{'sequence':'TEST'}},bytes([30,60,90])*160*120)
    time.sleep(.3);w.offer(bytes([90,60,30])*160*120);w.stop('escaped');w.thread.join(timeout=15)
    assert not w.thread.is_alive() and not w.error
    data=json.loads((root/(w.name+'.json')).read_text())
    assert video_info(root/data['filename'])['streams'][0]['codec_name']=='h264'
    return root,data


def test_pause_branch_repeat_and_escape_are_one_recording(tmp_path):
    writers=[]
    class Writer:
        def __init__(self,root,state,frame):
            self.state=state.copy();self.error='';self.thread=NS(is_alive=lambda:False,join=lambda **kw:None);self.frames=[frame];writers.append(self)
        def offer(self,frame):self.frames.append(frame)
        def stop(self,reason):self.reason=reason
    c=ScreenCapture(tmp_path,Writer);grab=lambda:b'frame'
    c.update({'epoch':'a:1','running':True,'armed':True},True,grab)
    c.update({'epoch':'a:2','running':True,'armed':True},True,grab)
    c.update({'epoch':'a:2','running':False,'paused':True,'reason':'input_stale'},True,grab)
    c.update({'epoch':'a:2','running':False,'paused':False,'reason':'escaped'},False,grab)
    assert c.active is writers[0] and len(writers)==1
    c.update({'epoch':'a:3','running':False,'paused':False,'reason':'escaped'},True,grab)
    assert c.active is None and writers[0].reason=='escaped'
    c.update({'epoch':'a:3','running':False,'reason':'escaped'},True,grab)
    assert len(writers)==1
    c.update({'epoch':'b:1','running':True,'armed':True},True,grab)
    assert len(writers)==2
    c.close();assert writers[1].reason=='visualizer_closed'


def stage(clip,root):
    local,data=clip;incoming=root/'video_incoming';incoming.mkdir(parents=True)
    data.update(size=(local/data['filename']).stat().st_size,sha256=digest(local/data['filename']))
    shutil.copyfile(local/data['filename'],incoming/(data['id']+'.mp4.pending'))
    (incoming/(data['id']+'.json.pending')).write_text(json.dumps(data))
    return data


def test_video_import_publication_ranges_and_idempotence(clip,tmp_path):
    root=tmp_path/'k5';data=stage(clip,root)
    receipt=import_video(root,data['id']);assert receipt['sha256']==data['sha256']
    assert import_video(root,data['id'])==receipt
    q=ArchiveQueue(root);assert len(q.rows())==1 and q.rows()[0]['kind']=='video'
    Archiver(root,'https://example.test',probe=lambda *a:True,delete_raw=True).step()
    row=q.rows()[0];assert row['state']=='done'
    messages=[];q.notify_once('test',lambda u,t:messages.append(t) or True)
    assert len(messages)==1 and '画面録画（MP4）' in messages[0]
    server=DownloadServer(('127.0.0.1',0),root);t=threading.Thread(target=server.serve_forever,daemon=True);t.start()
    try:
        url='http://127.0.0.1:'+str(server.server_port)+'/bags/'+json.loads(row['remote'])['token']+'/'+row['archive']
        r=requests.get(url,headers={'Range':'bytes=0-31'})
        assert r.status_code==206 and r.headers['Content-Type']=='video/mp4' and 'inline' in r.headers['Content-Disposition']
        assert len(r.content)==32
    finally:server.shutdown();server.server_close();t.join(timeout=2)


def test_corrupted_transfer_is_not_published(clip,tmp_path):
    root=tmp_path/'k5';data=stage(clip,root)
    (root/'video_incoming'/(data['id']+'.mp4.pending')).write_bytes(b'corrupted')
    with pytest.raises(ValueError,match='checksum'):import_video(root,data['id'])
    assert not ArchiveQueue(root).rows()


def test_transfer_failure_keeps_local_clip_and_retries(clip):
    root,data=clip;calls=[]
    def fail(args,**kwargs):raise subprocess.CalledProcessError(1,args)
    Transfer(root,'air-water@192.168.1.64',run=fail).step()
    path=root/(data['id']+'.json');saved=json.loads(path.read_text())
    assert saved['status']=='ready' and saved['error'] and (root/data['filename']).exists()
    saved['retry_at']=0;atomic_json(path,saved)
    def run(args,**kwargs):
        calls.append(args)
        return NS(stdout=json.dumps({'stored':True,'sha256':digest(root/data['filename']),'size':(root/data['filename']).stat().st_size}).encode())
    transfer=Transfer(root,'air-water@192.168.1.64',run=run);transfer.step()
    assert json.loads(path.read_text())['status']=='transferred'
    assert sum(c[0]=='rsync' for c in calls)==2
    transfer.step();assert len(calls)==4
    assert (root/data['filename']).exists()


def test_shared_retention_includes_video(clip,tmp_path):
    root=tmp_path/'k5';data=stage(clip,root);import_video(root,data['id'])
    w=Archiver(root,'https://example.test',probe=lambda *a:True);w.step()
    row=w.queue.rows()[0];w.limit=1;w.prune()
    assert w.queue.rows()[0]['pruned']==1
    assert not (root/'archives'/row['archive']).exists()


def test_stale_screen_capture_finishes_without_operator(tmp_path,monkeypatch):
    clock=[0.];monkeypatch.setattr('geniac_visualizer.screen_video.time.monotonic',lambda:clock[0])
    writers=[]
    class Writer:
        def __init__(self,root,state,frame):
            self.state=state;self.error='';self.thread=NS(is_alive=lambda:False);writers.append(self)
        def offer(self,frame):pass
        def stop(self,reason):self.reason=reason
    c=ScreenCapture(tmp_path,Writer)
    c.update({'epoch':'a:1','running':True},True,lambda:b'frame')
    clock[0]=1;c.update({},False,lambda:b'frame')
    clock[0]=37;c.update({},False,lambda:b'frame')
    assert c.active is None and writers[0].reason=='input_timeout'
