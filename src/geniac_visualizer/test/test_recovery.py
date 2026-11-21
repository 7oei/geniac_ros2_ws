import json
import os
import time
from geniac_visualizer.archive_queue import ArchiveQueue
from geniac_visualizer.recovery import recover_bags,recover_videos,recovery_lock


def test_bag_recovery_skips_live_writer_and_requeues_closed_bag(tmp_path,monkeypatch):
    q=ArchiveQueue(tmp_path);bag=tmp_path/'episode';bag.mkdir()
    db=bag/'episode.db3';db.write_bytes(b'db');os.utime(db,(1,1))
    q.started(bag,{})
    calls=[]
    def reindex(*args,**kwargs):
        calls.append(args)
        (bag/'metadata.yaml').write_text('rosbag2_bagfile_information:\n  message_count: 2\n  relative_file_paths: [episode.db3]\n')
    monkeypatch.setattr('geniac_visualizer.recovery.subprocess.run',reindex)
    with recovery_lock(q.directory/'episode.recording.lock'):
        recover_bags(q)
    assert not calls and q.rows()[0]['state']=='recording'
    recover_bags(q)
    assert len(calls)==1 and q.rows()[0]['state']=='queued'
    assert q.rows()[0]['outcome']=='interrupted_recovered'
    recover_bags(q);assert len(calls)==1


def test_recovery_failure_preserves_data_and_backs_off(tmp_path,monkeypatch):
    q=ArchiveQueue(tmp_path);bag=tmp_path/'episode';bag.mkdir()
    db=bag/'episode.db3';db.write_bytes(b'original');os.utime(db,(1,1));q.started(bag,{})
    def fail(*a,**k):raise RuntimeError()
    monkeypatch.setattr('geniac_visualizer.recovery.subprocess.run',fail)
    recover_bags(q)
    assert db.read_bytes()==b'original'
    assert q.rows()[0]['state']=='recording_error' and q.rows()[0]['retry_at']>time.time()


def test_video_recovery_preserves_episode_and_respects_lock(tmp_path,monkeypatch):
    name='screen_20261121T000000Z_'+'a'*32
    p=tmp_path/(name+'.partial.mp4');p.write_bytes(b'video');os.utime(p,(1,1))
    (tmp_path/(name+'.capture.json')).write_text(json.dumps(dict(id=name,created=1,sensor_started=2,episode='b'*32,story={'sequence':42})))
    monkeypatch.setattr('geniac_visualizer.recovery.video_info',lambda p:{'format':{'duration':'2.5'}})
    with recovery_lock(tmp_path/(name+'.capture.lock')):recover_videos(tmp_path)
    assert p.exists()
    recover_videos(tmp_path)
    d=json.loads((tmp_path/(name+'.json')).read_text())
    assert d['episode']=='b'*32 and d['story']['sequence']==42
    assert d['status']=='ready' and d['duration']==2.5
    assert not p.exists() and (tmp_path/(name+'.mp4')).exists()
