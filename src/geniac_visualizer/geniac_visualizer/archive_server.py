"""Only capability URLs for completed archives; no directory listing or arbitrary paths."""
import json
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlsplit
from pathlib import Path
from .archive_queue import ArchiveQueue


class DownloadServer(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,address,root):
        self.queue=ArchiveQueue(root);self.slots=threading.BoundedSemaphore(4)
        self.rate_lock=threading.Lock();self.next_send=0.
        super().__init__(address,DownloadHandler)
    def process_request(self,request,address):
        if not self.slots.acquire(blocking=False):self.shutdown_request(request);return
        super().process_request(request,address)
    def process_request_thread(self,request,address):
        try:super().process_request_thread(request,address)
        finally:self.slots.release()
    def pace(self,size):
        with self.rate_lock:
            now=time.monotonic();wait=max(0,self.next_send-now)
            self.next_send=max(now,self.next_send)+size/2_000_000
        if wait:time.sleep(wait)


class DownloadHandler(BaseHTTPRequestHandler):
    def setup(self):super().setup();self.connection.settimeout(30)
    def log_message(self,*args):pass  # Capability tokens must not enter access logs.
    def do_HEAD(self):self.download(False)
    def do_GET(self):self.download(True)
    def download(self,body):
        match=re.fullmatch(r'/bags/([A-Za-z0-9_-]{43})/([A-Za-z0-9_.-]+\.(?:tar\.zst|mp4))',urlsplit(self.path).path)
        if not match:self.send_error(404);return
        token,name=match.groups()
        row=next((r for r in self.server.queue.rows() if r['state'] in ('published','done') and not r['pruned']
                  and r['archive']==name and json.loads(r['remote'] or '{}').get('token')==token),None)
        if row is None:self.send_error(404);return
        path=self.server.queue.root/'archives'/name
        if path.parent.is_symlink():self.send_error(404);return
        try:fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
        except OSError:self.send_error(404);return
        with os.fdopen(fd,'rb') as stream:
            size=os.fstat(stream.fileno()).st_size;etag='"'+row['sha256']+'"'
            if size!=row['size']:self.send_error(503);return
            start,end=0,size-1;partial=False
            value=self.headers.get('Range')
            if value and self.headers.get('If-Range',etag)==etag:
                m=re.fullmatch(r'bytes=(\d*)-(\d*)',value)
                if m and (m[1] or m[2]):
                    if m[1]:start=int(m[1]);end=min(size-1,int(m[2])) if m[2] else size-1
                    else:start=max(0,size-int(m[2]))
                    partial=0<=start<=end<size
                if not partial:
                    self.send_response(416);self.send_header('Content-Range',f'bytes */{size}');self.end_headers();return
            self.send_response(206 if partial else 200)
            self.send_header('Content-Type','video/mp4' if name.endswith('.mp4') else 'application/zstd');self.send_header('Content-Length',str(end-start+1))
            self.send_header('Content-Disposition',('inline' if name.endswith('.mp4') else 'attachment')+f'; filename="{name}"')
            self.send_header('Accept-Ranges','bytes');self.send_header('ETag',etag)
            self.send_header('Cache-Control','private, no-store');self.send_header('X-Robots-Tag','noindex, nofollow')
            self.send_header('Referrer-Policy','no-referrer');self.send_header('X-Content-Type-Options','nosniff')
            if partial:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
            self.end_headers()
            if not body:return
            stream.seek(start);remaining=end-start+1
            try:
                while remaining:
                    block=stream.read(min(128*1024,remaining))
                    if not block:break
                    self.server.pace(len(block));self.wfile.write(block);remaining-=len(block)
            except (OSError,TimeoutError):pass
