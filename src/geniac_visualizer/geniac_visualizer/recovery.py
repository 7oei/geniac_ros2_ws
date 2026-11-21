"""Recover interrupted recordings without touching live writers or deleting source data."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import subprocess
import time
from .screen_video import atomic_json, video_info


@contextmanager
def recovery_lock(path):
    with path.open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        yield True


def open_files():
    """Legacy recordings have no lock: also exclude files still opened by this user."""
    paths=set()
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():continue
        try:
            if proc.stat().st_uid!=os.getuid():continue
            for fd in (proc/'fd').iterdir():
                try:paths.add(fd.resolve())
                except OSError:pass
        except OSError:continue
    return paths


def recover_bags(queue):
    opened=open_files()
    for row in queue.rows():
        if row['kind']!='bag' or row['state'] not in ('recording','recording_error'):continue
        if row['retry_at']>time.time():continue
        directory=queue.bag(row['name'])
        if not directory.is_dir():continue
        databases=list(directory.glob('*.db3'))
        if not databases or any(p.is_symlink() for p in databases):continue
        if any(p.resolve() in opened or time.time()-p.stat().st_mtime<60 for p in databases):continue
        with recovery_lock(queue.directory/(row['name']+'.recording.lock')) as acquired:
            if not acquired:continue
            try:
                # ROS reindex reads the existing SQLite files and rebuilds metadata.
                with (queue.directory/(row['name']+'.recovery.log')).open('ab') as log:
                    subprocess.run(['ros2','bag','reindex',str(directory)],check=True,
                                   stdout=log,stderr=subprocess.STDOUT,timeout=300)
                import yaml
                meta=yaml.safe_load((directory/'metadata.yaml').read_text())['rosbag2_bagfile_information']
                if not meta.get('relative_file_paths') or meta.get('message_count',0)<=0:raise ValueError('Empty recovered bag')
                queue.update(row['name'],state='queued',outcome='interrupted_recovered',error='',retry_at=0)
            except Exception as exc:
                queue.update(row['name'],state='recording_error',error='Recovery: '+type(exc).__name__,retry_at=time.time()+300)


def recover_videos(root):
    root=Path(root)
    opened=open_files()
    for journal in root.glob('screen_*.capture.json'):
        if journal.is_symlink():continue
        name=journal.name.removesuffix('.capture.json')
        from .video_transfer import ID
        if not ID.fullmatch(name):continue
        manifest=root/(name+'.json');pending=root/(name+'.partial.mp4');target=root/(name+'.mp4')
        if manifest.exists():continue
        source=target if target.exists() else pending
        if not source.is_file() or source.is_symlink():continue
        if source.resolve() in opened or time.time()-source.stat().st_mtime<60:continue
        with recovery_lock(root/(name+'.capture.lock')) as acquired:
            if not acquired:continue
            try:
                data=json.loads(journal.read_text())
                if data.get('retry_at',0)>time.time():continue
                info=video_info(source)
                if source==pending:pending.replace(target)
                data.update(id=name,filename=target.name,status='ready',outcome='interrupted_recovered',duration=float(info['format']['duration']))
                atomic_json(manifest,data)
            except Exception as exc:
                data=json.loads(journal.read_text())
                data.update(error='Recovery: '+type(exc).__name__,retry_at=time.time()+300)
                atomic_json(journal,data)
