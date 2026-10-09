# 삼바 승인카드 연동 — 승인요청 등록 / 결정 폴링 재개 / 만료·거부 / 연결 실패 / 이벤트 마스킹
import json

import httpx
import respx

from samba_agent.agents.contracts import AgentResult, OrderRef
from samba_agent.failures import FailReason
from samba_agent.gateway.wave_approval import (
    WaveApprovalRelay,
    WaveEventSink,
    payload_from_request,
    waiting_stage,
)
from samba_agent.queue.db import JobQueue
from samba_agent.wave.client import WaveClient

WAVE = 'http://wave.test'
API = f'{WAVE}/api/v1/internal/harness'


def client() -> WaveClient:
    return WaveClient(WAVE, 'tok', 'tenant-1')


def waiting_job(q: JobQueue, order_no: str = 'A1', wave_id: str = 'ord_A1'):
    """워커가 결제 직전에 멈춘 모양 그대로 — needs_human + '승인 대기: pay'."""
    job, _ = q.enqueue(order_no, 'intake', {}, None, wave_id=wave_id)
    claimed = q.claim()
    q.progress(claimed.id, agent='approval.pay', step='승인 대기: pay')
    q.finish(claimed.id, 'needs_human')
    return q.get_by_id(claimed.id)


REQ = {
    'kind': 'samba.approval',
    'stage': 'pay',
    'order_no': 'A1',
    'summary': '*결제 승인 요청* — 주문 A1 (MUSINSA)\n계정: buy-1 · 카드: 무신사머니\n원가: 32,210원 · 마진: 5.9%\n모드: 실제 반영',
    'evidence': [{'label': '배송지', 'detail': '수취인 홍길동 010-1234-5678 반영'}],
}


def test_요약에서_계정_카드_원가_마진을_뽑는다():
    p = payload_from_request(REQ)
    assert p['account'] == 'buy-1' and p['card'] == '무신사머니'
    assert p['cost'] == 32210 and p['margin_pct'] == 5.9
    assert p['evidence'][0]['label'] == '배송지'
    assert '5678' not in p['evidence'][0]['detail'] and '홍길동' not in p['evidence'][0]['detail']


def test_대기_단계_판별(tmp_path):
    q = JobQueue(tmp_path / 'q.sqlite')
    job = waiting_job(q)
    assert waiting_stage(job) == 'pay'
    q.enqueue('B1', 'intake', {}, None, wave_id='ord_B1')
    assert waiting_stage(q.get('ord_B1')) is None


@respx.mock
def test_승인요청을_백엔드에_올린다(tmp_path):
    q = JobQueue(tmp_path / 'q.sqlite')
    job = waiting_job(q)
    route = respx.post(f'{API}/orders/ord_A1/approval').mock(
        return_value=httpx.Response(200, json={'ok': True, 'approval_id': 'pa_1', 'state': 'pending'})
    )
    relay = WaveApprovalRelay(client(), q, lambda *a: None)
    relay.request(job, REQ)
    assert route.called
    body = json.loads(route.calls[0].request.content)
    assert body['stage'] == 'pay' and body['payload']['card'] == '무신사머니'
    assert '5678' not in body['summary']


@respx.mock
def test_승인되면_재개한다(tmp_path):
    q = JobQueue(tmp_path / 'q.sqlite')
    waiting_job(q)
    respx.get(f'{API}/orders/ord_A1/approval').mock(
        return_value=httpx.Response(200, json={'state': 'approved', 'by': 'su_boss'})
    )
    calls = []

    def resume(key, approved, by, stage):
        calls.append((key, approved, by, stage))
        return q.get(key)

    relay = WaveApprovalRelay(client(), q, resume)
    assert relay.poll_once() == 1
    assert calls == [('ord_A1', True, 'su_boss', 'pay')]


@respx.mock
def test_거부와_만료는_거부로_재개한다(tmp_path):
    for state, want_by in (('rejected', 'su_boss'), ('expired', 'expired')):
        q = JobQueue(tmp_path / f'q-{state}.sqlite')
        waiting_job(q)
        respx.get(f'{API}/orders/ord_A1/approval').mock(
            return_value=httpx.Response(
                200, json={'state': state, 'by': 'su_boss' if state == 'rejected' else None}
            )
        )
        calls = []
        relay = WaveApprovalRelay(client(), q, lambda *a: calls.append(a) or q.get(a[0]))
        assert relay.poll_once() == 1
        assert calls == [('ord_A1', False, want_by, 'pay')]


@respx.mock
def test_대기중이면_재개하지_않는다(tmp_path):
    q = JobQueue(tmp_path / 'q.sqlite')
    waiting_job(q)
    respx.get(f'{API}/orders/ord_A1/approval').mock(
        return_value=httpx.Response(200, json={'state': 'pending'})
    )
    calls = []
    relay = WaveApprovalRelay(client(), q, lambda *a: calls.append(a))
    relay._requested.add('ord_A1')
    assert relay.poll_once() == 0 and calls == []


@respx.mock
def test_요청이_없으면_다시_올린다(tmp_path):
    # 로봇 재기동 — 메모리의 요청 목록이 비어 있고 삼바에도 없다 → 카드를 띄운다
    q = JobQueue(tmp_path / 'q.sqlite')
    waiting_job(q)
    respx.get(f'{API}/orders/ord_A1/approval').mock(return_value=httpx.Response(200, json={'state': 'none'}))
    post = respx.post(f'{API}/orders/ord_A1/approval').mock(
        return_value=httpx.Response(200, json={'ok': True, 'approval_id': 'pa_2', 'state': 'pending'})
    )
    relay = WaveApprovalRelay(client(), q, lambda *a: None)
    assert relay.poll_once() == 0
    assert post.called and 'ord_A1' in relay._requested
    # 두 번째 주기엔 다시 올리지 않는다
    assert relay.poll_once() == 0 and post.call_count == 1


@respx.mock
def test_대기_상태가_아니면_재개하지_않는다(tmp_path):
    # resume 이 None(이미 다른 단계) 이어도 예외 없이 0
    q = JobQueue(tmp_path / 'q.sqlite')
    waiting_job(q)
    respx.get(f'{API}/orders/ord_A1/approval').mock(
        return_value=httpx.Response(200, json={'state': 'approved', 'by': 'x'})
    )
    relay = WaveApprovalRelay(client(), q, lambda *a: None)
    assert relay.poll_once() == 0


@respx.mock
def test_백엔드_연결_실패는_스레드를_죽이지_않는다(tmp_path):
    q = JobQueue(tmp_path / 'q.sqlite')
    waiting_job(q)
    respx.get(f'{API}/orders/ord_A1/approval').mock(side_effect=httpx.ConnectError('down'))
    relay = WaveApprovalRelay(client(), q, lambda *a: None)
    assert relay.poll_once() == 0
    # 승인요청 등록도 마찬가지
    respx.post(f'{API}/orders/ord_A1/approval').mock(side_effect=httpx.ConnectError('down'))
    relay.request(q.get('ord_A1'), REQ)
    assert 'ord_A1' not in relay._requested


@respx.mock
def test_이벤트_문장은_가린_뒤_보낸다(tmp_path):
    q = JobQueue(tmp_path / 'q.sqlite')
    job = waiting_job(q)
    route = respx.post(f'{API}/orders/ord_A1/events').mock(
        return_value=httpx.Response(200, json={'ok': True, 'count': 1})
    )
    WaveEventSink(client()).line(job, '배송지 반영 — 수취인 홍길동 · 010-1234-5678 서울 강남구')
    body = json.loads(route.calls[0].request.content)
    item = body['items'][0]
    assert item['code'] == 'system.report' and item['stage'] == 'system'
    assert '5678' not in item['message'] and '홍길동' not in item['message']


@respx.mock
def test_에이전트_결과는_단계_코드로_남는다():
    route = respx.post(f'{API}/orders/ord_A1/events').mock(
        return_value=httpx.Response(200, json={'ok': True, 'count': 1})
    )
    sink = WaveEventSink(client())
    order = OrderRef(order_no='A1', source='MUSINSA', seller='신세계몰', sku='S', qty=1, wave_id='ord_A1')
    ok = AgentResult(status='ok', reason='옵션 120, 계정 buy-1', payload={'account': 'buy-1', 'card': '무신사머니', 'cost': 32210})
    sink.agent_result({'order': order, 'dry_run': False}, 'buy', 'buyer.musinsa', ok, 1234, 1)
    fail = AgentResult(status='fail', reason='마진 미달', fail_reason=FailReason.MARGIN)
    sink.agent_result({'order': order}, 'buy', 'buyer.musinsa', fail, 10, 2)
    items = [json.loads(c.request.content)['items'][0] for c in route.calls]
    assert items[0]['code'] == 'buy.ok' and items[0]['severity'] == 'info'
    assert items[0]['pay_method'] == '무신사머니' and items[0]['detail']['cost'] == 32210
    assert items[1]['code'] == f'buy.{FailReason.MARGIN}' and items[1]['severity'] == 'error'
    assert items[1]['detail']['attempt'] == 2


@respx.mock
def test_이벤트_적재_실패는_삼킨다():
    respx.post(f'{API}/orders/ord_A1/events').mock(side_effect=httpx.ConnectError('down'))
    order = OrderRef(order_no='A1', source='MUSINSA', seller='x', sku='S', qty=1, wave_id='ord_A1')
    WaveEventSink(client()).agent_result(
        {'order': order}, 'buy', 'buyer.musinsa', AgentResult(status='ok', reason='r'), 1, 1
    )
