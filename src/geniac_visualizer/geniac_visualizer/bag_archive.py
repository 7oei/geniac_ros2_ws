"""Verified tar.zst archives, public-link readiness and bounded local retention."""
import hashlib
import http.client
import ipaddress
import socket
import ssl
import json
import os
import secrets
import shlex
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit
import requests
import yaml
from .archive_queue import ArchiveQueue


def read_env(path):
    result={}
    if path and Path(path).is_file():
        for line in Path(path).read_text().splitlines():
            key,sep,value=line.strip().removeprefix('export ').partition('=')
            if sep and key and not key.startswith('#'):
                parts=shlex.split(value,comments=True);result[key]=parts[0] if parts else ''
    return {**result,**os.environ}


def inventory(bag):
    if bag.is_symlink() or not bag.is_dir():raise ValueError('Invalid bag directory')
    metadata=bag/'metadata.yaml'
    info=yaml.safe_load(metadata.read_text())['rosbag2_bagfile_information']
    files=info['relative_file_paths']
    if not files:raise ValueError('Empty bag')
    for name in files:
        file=bag/name
        if file.resolve().parent!=bag.resolve() or not file.is_file():raise ValueError('Invalid bag storage path')
    result={}
    for p in sorted(bag.rglob('*')):
        if p.is_symlink():raise ValueError('Symlink in bag')
        if p.is_dir():continue
        if not p.is_file():raise ValueError('Non-regular file in bag')
        stat=p.stat();result[str(p.relative_to(bag))]=[stat.st_size,stat.st_mtime_ns]
    return result


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def compress(bag,directory):
    directory.mkdir(parents=True,exist_ok=True)
    before=inventory(bag)
    partial=directory/(bag.name+'.partial')
    if partial.is_symlink():raise ValueError('Invalid archive temporary path')
    try:
        subprocess.run(['nice','-n','10','tar','-I','zstd -T1 -3','-cf',str(partial),'-C',str(bag.parent),bag.name],
                       check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        subprocess.run(['nice','-n','10','tar','-I','zstd','-tf',str(partial)],check=True,
                       stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        if inventory(bag)!=before:raise ValueError('Bag changed during compression')
        checksum=digest(partial)
        target=directory/(bag.name+'_'+checksum[:16]+'.tar.zst')
        with partial.open('rb') as f:os.fsync(f.fileno())
        partial.replace(target)
        fd=os.open(directory,os.O_RDONLY)
        try:os.fsync(fd)
        finally:os.close(fd)
        return target,checksum,before
    finally:
        if partial.exists() and not partial.is_symlink():partial.unlink()


def public_connection(url,method='HEAD',headers=None):
    """Resolve through public DNS, bypassing Tailscale's private split DNS."""
    u=urlsplit(url)
    if u.scheme!='https' or not u.hostname or u.port not in (None,443):raise ValueError('Invalid public HTTPS URL')
    dns=requests.get('https://dns.google/resolve',params={'name':u.hostname,'type':'A'},timeout=(10,15))
    dns.raise_for_status()
    addresses=[a['data'] for a in dns.json().get('Answer',[]) if a.get('type')==1 and ipaddress.ip_address(a['data']).is_global]
    if not addresses:raise ValueError('No public IPv4 address for download host')
    for address in addresses:
        connection=http.client.HTTPSConnection(u.hostname,timeout=20)
        try:
            raw=socket.create_connection((address,443),timeout=20)
            try:connection.sock=ssl.create_default_context().wrap_socket(raw,server_hostname=u.hostname)
            except Exception:raw.close();raise
            connection.request(method,u.path or '/',headers=headers or {})
            return connection,connection.getresponse()
        except (OSError,http.client.HTTPException):connection.close()
    raise OSError('Public download endpoint unavailable')


def public_ready(url,size,checksum):
    connection=None
    try:
        connection,response=public_connection(url)
        return response.status==200 and int(response.getheader('Content-Length','-1'))==size and response.getheader('ETag')=='"'+checksum+'"'
    except (requests.RequestException,OSError,ValueError,http.client.HTTPException):return False
    finally:
        if connection:connection.close()


class Archiver:
    def __init__(self,root,base_url,limit=100_000_000_000,delete_raw=False,probe=public_ready):
        self.queue=ArchiveQueue(root);self.directory=self.queue.root/'archives'
        self.directory.mkdir(exist_ok=True)
        if self.directory.is_symlink():raise ValueError('Invalid archive directory')
        u=urlsplit(base_url)
        if u.scheme!='https' or not u.hostname or u.username or u.password or u.query or u.fragment or u.path not in ('','/'):
            raise ValueError('A public HTTPS origin is required')
        if limit<=0:raise ValueError('Archive limit must be positive')
        self.base=base_url.rstrip('/');self.limit=limit;self.delete_raw=delete_raw;self.probe=probe
    def archive_path(self,name):
        if Path(name).name!=name or not name.endswith(('.tar.zst','.mp4')):raise ValueError('Invalid archive name')
        p=self.directory/name
        if p.is_symlink():raise ValueError('Invalid archive path')
        return p
    def step(self):
        # rosbag creates metadata on clean closure; recover a recorder interrupted
        # after writing metadata but before it could update this persistent queue.
        for row in self.queue.rows():
            metadata=self.queue.bag(row['name'])/'metadata.yaml'
            if row['state']=='recording' and metadata.is_file() and time.time()-metadata.stat().st_mtime>30:
                self.queue.finished(self.queue.bag(row['name']),'interrupted/recovered')
        for row in self.queue.rows():
            if row['state'] in ('recording','recording_error','done') or row['retry_at']>time.time():continue
            try:self.process(row)
            except Exception as exc:
                attempts=row['attempts']+1
                # Do not expose request URLs (which contain download capabilities).
                error=str(exc) if isinstance(exc,ValueError) else type(exc).__name__
                self.queue.update(row['name'],attempts=attempts,retry_at=time.time()+min(300,5*2**min(attempts,6)),error=error[:240])
            break
        self.prune()
    def process(self,row):
        bag=self.queue.bag(row['name'])
        if not row['archive']:
            path,sha,files=compress(bag,self.directory)
            self.queue.update(row['name'],archive=path.name,sha256=sha,inventory=json.dumps(files),size=path.stat().st_size,state='compressed')
            row.update(archive=path.name,sha256=sha,inventory=json.dumps(files),size=path.stat().st_size,state='compressed')
        path=self.archive_path(row['archive'])
        if not path.is_file() or digest(path)!=row['sha256']:raise ValueError('Archive checksum mismatch; original bag retained')
        receipt=json.loads(row['remote']) if row['remote'] else {'token':secrets.token_urlsafe(32)}
        receipt['url']=self.base+'/bags/'+receipt['token']+'/'+path.name
        self.queue.published(row['name'],receipt)
        if not self.probe(receipt['url'],row['size'],row['sha256']):raise ValueError('Public download is not ready; original bag retained')
        if row['kind']=='bag' and self.delete_raw and bag.exists():
            if inventory(bag)!=json.loads(row['inventory']):raise ValueError('Original bag changed; deletion refused')
            shutil.rmtree(bag)
        self.queue.completed(row['name'])
    def prune(self):
        # Never remove unfinished archives or arbitrary files not owned by this queue.
        rows=self.queue.rows();total=sum(p.stat().st_size for p in self.directory.iterdir() if p.name.endswith(('.tar.zst','.mp4')) and p.is_file() and not p.is_symlink())
        for row in rows:
            if total<=self.limit:break
            if row['state']!='done' or row['pruned'] or not row['archive']:continue
            path=self.archive_path(row['archive'])
            if path.exists():
                size=path.stat().st_size;path.unlink();total-=size
            self.queue.update(row['name'],pruned=1)
            if row['kind']=='bag':
                from .scenario_audio import prune_audio
                prune_audio(self.queue.root,row['name'])
        return total
