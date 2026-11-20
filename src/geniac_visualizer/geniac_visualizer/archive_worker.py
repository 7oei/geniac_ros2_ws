"""Separate CPU/network worker: never compress or notify in the ROS executor."""
import argparse
import fcntl
import signal
import threading
from pathlib import Path
from .archive_queue import ArchiveQueue
from .bag_archive import Archiver,read_env
from .archive_server import DownloadServer
from .notifications import send


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',default=str(Path.home()/'geniac_bags'))
    parser.add_argument('--env',default=str(Path.home()/'geniac_ros2_ws/.env'))
    parser.add_argument('--port',type=int,default=8765)
    args=parser.parse_args()
    queue=ArchiveQueue(args.root)
    lock=(queue.directory/'worker.lock').open('w')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    server=DownloadServer(('127.0.0.1',args.port),args.root)
    closed=threading.Event()
    def shutdown(*_):closed.set()
    signal.signal(signal.SIGTERM,shutdown);signal.signal(signal.SIGINT,shutdown)
    def notifications():
        while not closed.is_set():
            try:queue.notify_once(read_env(args.env).get('DISCORD_WEBHOOK_URL',''),send)
            except Exception:print('Archive notification queue unavailable; retrying',flush=True)
            closed.wait(1)
    threads=[threading.Thread(target=server.serve_forever,daemon=True),threading.Thread(target=notifications,daemon=True)]
    for t in threads:t.start()
    try:
        while not closed.is_set():
            try:
                config=read_env(args.env)
                Archiver(args.root,config.get('GENIAC_ARCHIVE_BASE_URL',''),
                         limit=int(config.get('GENIAC_ARCHIVE_MAX_BYTES','100000000000')),
                         delete_raw=config.get('GENIAC_ARCHIVE_DELETE_RAW','false').lower()=='true').step()
            except Exception as exc:print('Archive worker waiting: '+type(exc).__name__,flush=True)
            closed.wait(2)
    finally:
        closed.set();server.shutdown();server.server_close()
        for t in threads:t.join(timeout=6)
        lock.close()
