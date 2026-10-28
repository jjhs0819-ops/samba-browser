# 소싱처 자동취소 — 삼바 로봇 취소 하네스 API 클라이언트 · 텔레그램 카드 · 설정 스위치
import json

import httpx
import pytest
import respx

from samba_agent.failures import FailReason
from samba_agent.ops.telegram import TelegramNotifier
from samba_agent.settings import load_settings
from samba_agent.wave.client import RobotCancelItem, WaveClient, WaveError

BASE = 'https://wave.test'
API = f'{BASE}/api/v1/internal/harness'
TOKEN = 'test-token-not-a-real-secret'  # 테스트 전용 가짜 값
TENANT = 'tenant-1'

ITEM_JSON = {
    'id': 'rc_01J',
    'order_id': 'ord_1',
    'order_number': '20261028001',
    'source_site': 'MUSINSA',
    'sourcing_order_number': 'M20261028777',
    'account_username': 'buyer01',
    'mode': 'cancel',
    'bundle_count': 1,
    'shipping_status': '취소요청',
    'tracking_number': None,
    'attempts': 0,
}


def client() -> WaveClient:
    return WaveClient(BASE, TOKEN, TENANT)


# ---- robot_cancels ----


@respx.mock
def test_취소_목록은_헤더와_limit_을_붙여_부르고_항목을_돌려준다():
    route = respx.get(f'{API}/robot-cancels').mock(
        return_value=httpx.Response(200, json={'items': [ITEM_JSON], 'count': 1})
    )
    items = client().robot_cancels(limit=5)
    request = route.calls[0].request
    assert request.headers['X-Internal-Token'] == TOKEN
    assert request.headers['X-Tenant-Id'] == TENANT
    # sites 를 안 주면 파라미터 자체를 보내지 않는다(전부)
    assert dict(httpx.QueryParams(request.url.query.decode())) == {'limit': '5'}
    assert len(items) == 1
    item = items[0]
    assert isinstance(item, RobotCancelItem)
    assert item.id == 'rc_01J'
    assert item.order_number == '20261028001'
    assert item.source_site == 'MUSINSA'
    assert item.sourcing_order_number == 'M20261028777'
    assert item.account_username == 'buyer01'
    assert item.mode == 'cancel'
    assert item.bundle_count == 1
    assert item.shipping_status == '취소요청'
    assert item.tracking_number is None
    assert item.attempts == 0


@respx.mock
def test_취소_목록은_sites_를_쉼표_목록으로_보낸다():
    route = respx.get(f'{API}/robot-cancels').mock(
        return_value=httpx.Response(200, json={'items': [], 'count': 0})
    )
    assert client().robot_cancels(limit=20, sites={'MUSINSA', 'ABCmart'}) == []
    params = dict(httpx.QueryParams(route.calls[0].request.url.query.decode()))
    assert params['limit'] == '20'
    assert set(params['sites'].split(',')) == {'MUSINSA', 'ABCmart'}


@respx.mock
def test_취소_목록은_빈_sites_면_파라미터를_보내지_않는다():
    route = respx.get(f'{API}/robot-cancels').mock(
        return_value=httpx.Response(200, json={'items': [], 'count': 0})
    )
    client().robot_cancels(sites=set())
    assert dict(httpx.QueryParams(route.calls[0].request.url.query.decode())) == {'limit': '20'}


@respx.mock
def test_취소_목록_항목은_계정_없음과_check_모드를_받는다():
    respx.get(f'{API}/robot-cancels').mock(
        return_value=httpx.Response(
            200,
            json={
                'items': [
                    {
                        **ITEM_JSON,
                        'account_username': None,
                        'mode': 'check',
                        'bundle_count': 2,
                        'tracking_number': '1234',
                        'attempts': 1,
                    }
                ],
                'count': 1,
            },
        )
    )
    item = client().robot_cancels()[0]
    assert item.account_username is None
    assert item.mode == 'check'
    assert item.bundle_count == 2
    assert item.tracking_number == '1234'
    assert item.attempts == 1


@respx.mock
def test_취소_목록_403_은_권한_실패다():
    respx.get(f'{API}/robot-cancels').mock(
        return_value=httpx.Response(403, json={'detail': 'forbidden'})
    )
    with pytest.raises(WaveError) as exc:
        client().robot_cancels()
    assert exc.value.reason is FailReason.PERMISSION_DENIED
    assert TOKEN not in str(exc.value)


# ---- post_robot_cancel_result ----


@respx.mock
def test_결과_회신은_경로와_바디를_맞춰_보내고_새_state_를_돌려준다():
    route = respx.post(f'{API}/robot-cancels/rc_01J/result').mock(
        return_value=httpx.Response(200, json={'ok': True, 'state': 'done'})
    )
    assert client().post_robot_cancel_result('rc_01J', 'cancelled') == 'done'
    assert json.loads(route.calls[0].request.content) == {'outcome': 'cancelled', 'reason': ''}


@respx.mock
def test_결과_회신은_failed_사유를_같이_보낸다():
    route = respx.post(f'{API}/robot-cancels/rc_01J/result').mock(
        return_value=httpx.Response(200, json={'ok': True, 'state': 'retry'})
    )
    state = client().post_robot_cancel_result('rc_01J', 'failed', reason='취소 버튼 없음')
    assert state == 'retry'
    assert json.loads(route.calls[0].request.content) == {
        'outcome': 'failed',
        'reason': '취소 버튼 없음',
    }


@respx.mock
def test_결과_회신_404_는_WaveError_다():
    respx.post(f'{API}/robot-cancels/rc_none/result').mock(
        return_value=httpx.Response(404, json={'detail': 'not found'})
    )
    with pytest.raises(WaveError) as exc:
        client().post_robot_cancel_result('rc_none', 'cancelled')
    assert exc.value.status == 404


# ---- TelegramNotifier ----


def _telegram(handler) -> TelegramNotifier:
    return TelegramNotifier(
        'bot-token-fake', 'chat-1', client=httpx.Client(transport=httpx.MockTransport(handler))
    )


def test_카드는_HTML_로_보내고_꺾쇠를_이스케이프한다():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={'ok': True})

    ok = _telegram(handler).card('warn', '제목 <A>', '결론 & 끝', '할일')
    assert ok is True
    request = seen[0]
    assert request.method == 'POST'
    assert request.url == httpx.URL('https://api.telegram.org/botbot-token-fake/sendMessage')
    body = json.loads(request.content)
    assert body['chat_id'] == 'chat-1'
    assert body['parse_mode'] == 'HTML'
    assert body['disable_web_page_preview'] is True
    assert body['text'] == (
        '🟡 <b>제목 &lt;A&gt;</b>\n<blockquote>결론 &amp; 끝\n👉 할일</blockquote>'
    )


@pytest.mark.parametrize(('level', 'emoji'), [('ok', '🟢'), ('warn', '🟡'), ('bad', '🔴')])
def test_카드_이모지는_수준별로_정해져_있다(level, emoji):
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content)['text'])
        return httpx.Response(200, json={'ok': True})

    assert _telegram(handler).card(level, '제목', '결론', '할일') is True
    assert seen[0].startswith(f'{emoji} <b>제목</b>')


def test_카드는_500_이면_False_다():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text='boom')

    assert _telegram(handler).card('bad', '제목', '결론', '할일') is False


def test_카드는_연결_실패에도_예외_없이_False_다():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError('down')

    assert _telegram(handler).card('ok', '제목', '결론', '할일') is False


def test_카드는_ok_false_응답이면_False_다():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={'ok': False, 'description': 'chat not found'})

    assert _telegram(handler).card('ok', '제목', '결론', '할일') is False


def test_토큰은_repr_에_나오지_않는다():
    notifier = TelegramNotifier('bot-token-fake', 'chat-1')
    assert 'bot-token-fake' not in repr(notifier)
    assert 'bot-token-fake' not in str(notifier)


# ---- settings ----


def test_자동취소_스위치_파싱(monkeypatch):
    monkeypatch.setenv('SAMBA_BRIDGE_TOKEN', 'f' * 64)
    monkeypatch.delenv('SAMBA_AUTO_CANCEL', raising=False)
    s = load_settings(env_file=None)
    assert s.auto_cancel == 'false'
    assert s.auto_cancel_sites() == set()
    monkeypatch.setenv('SAMBA_AUTO_CANCEL', 'true')
    assert load_settings(env_file=None).auto_cancel_sites() == 'all'
    monkeypatch.setenv('SAMBA_AUTO_CANCEL', 'MUSINSA, LOTTEON,')
    assert load_settings(env_file=None).auto_cancel_sites() == {'MUSINSA', 'LOTTEON'}
    monkeypatch.setenv('SAMBA_AUTO_CANCEL', 'false')
    assert load_settings(env_file=None).auto_cancel_sites() == set()


def test_자동취소_설정_기본값과_텔레그램_값(monkeypatch):
    monkeypatch.setenv('SAMBA_BRIDGE_TOKEN', 'f' * 64)
    for name in (
        'SAMBA_TELEGRAM_BOT_TOKEN',
        'SAMBA_TELEGRAM_CHAT_ID',
        'SAMBA_AUTO_CANCEL_INTERVAL_S',
    ):
        monkeypatch.delenv(name, raising=False)
    s = load_settings(env_file=None)
    assert s.telegram_bot_token is None
    assert s.telegram_chat_id is None
    assert s.auto_cancel_interval_s == 300
    monkeypatch.setenv('SAMBA_TELEGRAM_BOT_TOKEN', 'tg-token-fake')
    monkeypatch.setenv('SAMBA_TELEGRAM_CHAT_ID', '12345')
    monkeypatch.setenv('SAMBA_AUTO_CANCEL_INTERVAL_S', '60')
    s = load_settings(env_file=None)
    assert s.telegram_bot_token is not None
    assert s.telegram_bot_token.get_secret_value() == 'tg-token-fake'
    assert 'tg-token-fake' not in repr(s)  # SecretStr — 로그에 새지 않는다
    assert s.telegram_chat_id == '12345'
    assert s.auto_cancel_interval_s == 60
