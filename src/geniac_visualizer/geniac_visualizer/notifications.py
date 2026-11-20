"""Entry notifications are opt-in, rate-limited, and independent of playback."""
from urllib.parse import urlsplit
import re
import requests

class EntryGate:
    def __init__(self,cooldown=60.,absence=5.):
        self.cooldown=cooldown;self.absence=absence;self.last_notify=-1e9;self.last_seen=None;self.present=False
    def update(self,tracks,now,valid=True):
        if self.last_seen is not None and now-self.last_seen>self.absence:self.present=False
        if not valid:return False
        if not tracks:return False
        entry=not self.present;self.present=True;self.last_seen=now
        if entry and now-self.last_notify>=self.cooldown:
            self.last_notify=now;return True
        return False

def validate_webhook(webhook):
    """Accept native Discord incoming webhook URLs; never include tokens in errors."""
    try:
        u = urlsplit(webhook)
        valid = (u.scheme == 'https' and u.hostname in ('discord.com', 'discordapp.com')
                 and u.port in (None, 443) and not u.username and not u.password
                 and not u.query and not u.fragment
                 and re.fullmatch(r'/api/(?:v[0-9]+/)?webhooks/[0-9]+/[A-Za-z0-9_-]+', u.path))
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise ValueError('Invalid Discord incoming webhook URL')


def send(webhook, text, transport=requests.post):
    validate_webhook(webhook)
    if not isinstance(text, str) or not 1 <= len(text) <= 2000:
        raise ValueError('Discord notification must contain 1..2000 characters')
    try:
        response = transport(webhook, params={'wait': 'true'},
                             json={'content': text, 'allowed_mentions': {'parse': []}},
                             timeout=5, allow_redirects=False)
        return response.status_code == 200
    except requests.RequestException:
        return False
