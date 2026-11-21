"""Local files only, one owned playback process, bounded stop and no system volume edits."""
import subprocess
import tempfile

class Player:
    def __init__(self,volume=80,dry_run=True,spawn=subprocess.Popen):
        if not 0<=volume<=100:raise ValueError('Volume must be 0..100')
        self.volume=volume;self.dry_run=dry_run;self.spawn=spawn;self.process=None;self.error_file=None;self.last_error=''

    def stop(self):
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
                try:self.process.wait(timeout=.1)
                except subprocess.TimeoutExpired:
                    self.process.kill();self.process.wait(timeout=.1)
            self.process=None
        if self.error_file is not None:
            self.error_file.close();self.error_file=None

    def play(self,path,duration,offset=0.):
        self.stop();self.last_error=''
        if self.dry_run:return
        if path is None or not path.is_file():raise ValueError('Audio file missing')
        self.error_file=tempfile.TemporaryFile()
        self.process=self.spawn(['ffplay','-nodisp','-autoexit','-loglevel','error',
            '-volume',str(self.volume),'-ss',str(max(0.,offset)),'-t',str(duration),str(path)],
            stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=self.error_file)

    def failed(self):
        code=self.process.poll() if self.process is not None else None
        if code in (None,0):return False
        detail=''
        if self.error_file is not None:
            self.error_file.seek(0,2);size=self.error_file.tell()
            self.error_file.seek(max(0,size-2000))
            detail=self.error_file.read().decode('utf-8',errors='replace').strip()
        self.last_error=f'ffplay exit={code}: {detail}'
        return True
