"""Persistent approval gate; approving resumes API use, never purchases credit."""
import json
from pathlib import Path
import time
import uuid


class BillingRequired(RuntimeError):
    def __init__(self,provider='OpenAI',reason='quota_or_payment_required'):
        super().__init__(provider+': additional billing approval required')
        self.provider=provider;self.reason=reason


def state(root):
    path=Path(root)/'billing.json'
    if not path.exists():return {'blocked':False}
    try:return json.loads(path.read_text())
    except (OSError,ValueError):return {'blocked':True,'provider':'不明','reason':'billing_state_unreadable'}


def save(root,data):
    path=Path(root)/'billing.json';path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name('billing.'+uuid.uuid4().hex+'.tmp')
    temp.write_text(json.dumps(data,ensure_ascii=False));temp.replace(path)


def block(root,error):
    save(root,{'blocked':True,'provider':error.provider,'reason':error.reason,'detected_at':time.time()})


def approve(root):
    save(root,{'blocked':False,'approved_at':time.time()})


def guard(config):
    root=config.get('_billing_root')
    if root:
        current=state(root)
        if current.get('blocked'):raise BillingRequired(current.get('provider','OpenAI'),current.get('reason','quota_or_payment_required'))


def check_response(response,provider='OpenAI'):
    if response.status_code==200:return
    try:
        error=response.json().get('error',{})
        code=error.get('code') or error.get('type') if isinstance(error,dict) else ''
    except (ValueError,AttributeError,TypeError):code=''
    # Ordinary rate limiting is NOT proof that payment is needed.
    if response.status_code==402 or code in ('insufficient_quota','billing_hard_limit_reached','billing_not_active','billing_limit_reached','usage_limit_reached'):
        raise BillingRequired(provider,code or 'payment_required')
