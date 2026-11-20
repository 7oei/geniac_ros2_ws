"""Discord request tests use injected transports and never send messages."""
import pytest
import requests
from geniac_visualizer.notifications import send, validate_webhook

URL='https://discord.com/api/webhooks/123456/test-token'

@pytest.mark.parametrize('status,ok',[(200,True),(204,False),(400,False),(401,False),(404,False),(429,False),(500,False)])
def test_confirmed_delivery_and_failures(status,ok):
    calls=[]
    def post(url,**kwargs):
        calls.append((url,kwargs))
        return type('Response',(),{'status_code':status})()
    assert send(URL,'鹿候補 2 頭 @everyone',post) is ok
    assert len(calls)==1
    assert calls[0][1]['json']=={'content':'鹿候補 2 頭 @everyone','allowed_mentions':{'parse':[]}}
    assert calls[0][1]['params']=={'wait':'true'}
    assert calls[0][1]['allow_redirects'] is False

@pytest.mark.parametrize('url',[
    'http://discord.com/api/webhooks/123/token',
    'https://example.com/api/webhooks/123/token',
    'https://discord.com.evil.test/api/webhooks/123/token',
    'https://user:password@discord.com/api/webhooks/123/token',
    'https://discord.com/api/webhooks/123/token?wait=false',
    'https://discord.com/api/webhooks/123/token#fragment',
    'https://discord.com/api/webhooks/123/token/slack',
    'https://discord.com/api/webhooks/123/',
    'https://discord.com:invalid/api/webhooks/123/token',
])
def test_reject_invalid_urls_without_exposing_token(url):
    with pytest.raises(ValueError,match='Invalid Discord incoming webhook URL') as err:
        send(url,'test',lambda *a,**k:pytest.fail('network called'))
    assert url not in str(err.value)

@pytest.mark.parametrize('url',[URL,'https://discord.com/api/v10/webhooks/123/token','https://discordapp.com/api/webhooks/123/token'])
def test_supported_native_urls(url):
    validate_webhook(url)

def test_network_timeout_is_failure_without_retry():
    calls=[]
    def post(*a,**k):
        calls.append(1);raise requests.Timeout('do not log webhook/token')
    assert not send(URL,'test',post)
    assert len(calls)==1

@pytest.mark.parametrize('text',['','x'*2001])
def test_content_limit(text):
    with pytest.raises(ValueError):send(URL,text,lambda *a,**k:pytest.fail('network called'))
