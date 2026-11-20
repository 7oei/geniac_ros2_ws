import hashlib
import json
import os
from pathlib import Path
import threading
import time
import requests
import pytest
import yaml
from geniac_visualizer.archive_queue import ArchiveQueue
from geniac_visualizer.bag_archive import Archiver,compress,inventory,digest
from geniac_visualizer.archive_server import DownloadServer


def bag(root,name='20261120T120000Z_test'):
    path=root/name;path.mkdir(parents=True)
    (path/'data.db3').write_bytes(b'camera-and-lidar'*1000)
    (path/'metadata.yaml').write_text(yaml.safe_dump({'rosbag2_bagfile_information':{'relative_file_paths':['data.db3']}}))
    return path


def queued(root,name='20261120T120000Z_test'):
    path=bag(root,name);q=ArchiveQueue(root)
    q.started(path,{'sequence':123,'title':'試験シナリオ'});q.finished(path,'escaped')
    return path,q


def test_verified_archive_public_ready_then_delete_original_and_notify(tmp_path):
    path,q=queued(tmp_path)
    worker=Archiver(tmp_path,'https://example.test',delete_raw=True,probe=lambda *a:True)
    worker.step();row=q.rows()[0]
    assert row['state']=='done' and not path.exists()
    assert digest(tmp_path/'archives'/row['archive'])==row['sha256']
    calls=[];q.notify_once('test',lambda u,t:calls.append(t) or True)
    assert len(calls)==2 and '再生を開始' in calls[0] and 'ダウンロード準備' in calls[1]
    assert 'https://example.test/bags/' in calls[1]
    worker.step();q.notify_once('test',lambda *a:pytest.fail('duplicate notification'))


def test_unavailable_public_endpoint_keeps_raw_and_resumes_without_recompression(tmp_path):
    path,q=queued(tmp_path)
    w=Archiver(tmp_path,'https://example.test',delete_raw=True,probe=lambda *a:False)
    w.step();row=q.rows()[0]
    assert path.is_dir() and row['state']=='published' and row['error']
    token=json.loads(row['remote'])['token'];archive=tmp_path/'archives'/row['archive'];mtime=archive.stat().st_mtime_ns
    q.update(path.name,retry_at=0)
    w=Archiver(tmp_path,'https://example.test',delete_raw=True,probe=lambda *a:True);w.step()
    row=q.rows()[0]
    assert row['state']=='done' and not path.exists() and archive.stat().st_mtime_ns==mtime
    assert json.loads(row['remote'])['token']==token


def test_changed_source_or_corrupt_archive_never_deletes_original(tmp_path):
    path,q=queued(tmp_path)
    w=Archiver(tmp_path,'https://example.test',delete_raw=True,probe=lambda *a:False);w.step()
    (path/'data.db3').write_bytes(b'changed')
    q.update(path.name,retry_at=0);w.probe=lambda *a:True;w.step()
    assert path.exists() and 'changed' in q.rows()[0]['error']
    (tmp_path/'archives'/q.rows()[0]['archive']).write_bytes(b'corrupt')
    q.update(path.name,retry_at=0);w.step()
    assert path.exists() and 'checksum' in q.rows()[0]['error']


def test_retention_removes_oldest_completed_only(tmp_path):
    _,q=queued(tmp_path,'old')
    w=Archiver(tmp_path,'https://example.test',probe=lambda *a:True);w.step()
    time.sleep(.01);queued(tmp_path,'new');w.step()
    old,new=q.rows();newsize=new['size']
    w.limit=newsize;assert w.prune()==newsize
    assert q.rows()[0]['pruned']==1 and q.rows()[1]['pruned']==0
    assert not (tmp_path/'archives'/old['archive']).exists()
    assert (tmp_path/'archives'/new['archive']).exists()


def test_notification_failures_survive_restart(tmp_path):
    path,q=queued(tmp_path)
    q.started(path,{'sequence':123})
    q.notify_once('test',lambda *a:False)
    with q.connect() as c:
        assert c.execute('SELECT COUNT(*) FROM outbox').fetchone()[0]==1
        c.execute('UPDATE outbox SET retry_at=0')
    calls=[];ArchiveQueue(tmp_path).notify_once('test',lambda u,t:calls.append(t) or True)
    assert len(calls)==1


def test_symlink_and_unfinished_bags_are_not_compressed(tmp_path):
    path=bag(tmp_path);(path/'secret').symlink_to('/etc/passwd')
    with pytest.raises(ValueError,match='Symlink'):compress(path,tmp_path/'archives')
    other=tmp_path/'unfinished';other.mkdir()
    with pytest.raises(FileNotFoundError):compress(other,tmp_path/'archives')
    q=ArchiveQueue(tmp_path)
    with pytest.raises(ValueError):q.bag('../outside')


def test_capability_download_head_range_and_no_file_listing(tmp_path):
    _,q=queued(tmp_path)
    Archiver(tmp_path,'https://example.test',probe=lambda *a:True).step();row=q.rows()[0]
    server=DownloadServer(('127.0.0.1',0),tmp_path)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base='http://127.0.0.1:'+str(server.server_port)
    path='/bags/'+json.loads(row['remote'])['token']+'/'+row['archive']
    try:
        assert requests.get(base+'/').status_code==404
        assert requests.get(base+'/.archive/queue.sqlite3').status_code==404
        assert requests.get(base+path.replace('/bags/','/bags/wrong')).status_code==404
        response=requests.head(base+path);assert response.status_code==200
        assert int(response.headers['Content-Length'])==row['size']
        assert response.headers['ETag']=='"'+row['sha256']+'"'
        data=requests.get(base+path).content;assert hashlib.sha256(data).hexdigest()==row['sha256']
        r=requests.get(base+path,headers={'Range':'bytes=2-9'});assert r.status_code==206 and r.content==data[2:10]
        r=requests.get(base+path,headers={'Range':'bytes=-7'});assert r.status_code==206 and r.content==data[-7:]
        assert requests.get(base+path,headers={'Range':'bytes=99999999-'}).status_code==416
        q.update(row['name'],pruned=1)
        assert requests.get(base+path).status_code==404
    finally:server.shutdown();server.server_close();thread.join(timeout=2)


def test_recovery_waits_for_recorder_completion_callback(tmp_path):
    path=bag(tmp_path);q=ArchiveQueue(tmp_path);q.started(path,{})
    w=Archiver(tmp_path,'https://example.test',probe=lambda *a:True)
    w.step();assert q.rows()[0]['state']=='recording'
    os.utime(path/'metadata.yaml',(time.time()-60,time.time()-60))
    w.step();assert q.rows()[0]['state']=='done'
    assert q.rows()[0]['outcome']=='interrupted/recovered'
