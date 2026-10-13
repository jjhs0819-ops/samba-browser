# 무신사 결제 규칙(사용자 2026-10-12) — 현대카드 청구할인 우선 · 농협 즉시할인 · 폰결제 할인 정지 · 탭 소실 재구성
import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from samba_agent.agents.buyer import (
    billing_factor,
    clean_pay_card,
    hyundai_choice,
    is_nh_tile,
    other_tiles_over,
)
from samba_agent.agents.contracts import AgentResult, OrderRef
from samba_agent.agents.payer import order_tab_gone
from samba_agent.agents.recorder import wave_notes
from samba_agent.agents.registry import Registry
from samba_agent.failures import FailReason
from samba_agent.settings import DEFAULT_ROOT
from samba_agent.sources import default_sources
from samba_agent.supervisor.graph import build_supervisor

# 실기 2026-10-12 후드집업 주문서에서 읽은 값
INFO = {
    'ok': True,
    'base_cost': 76300,
    'money': {'cost': 76300, 'balance': 197625, 'reward': 0, 'points_used': 0},
    'pay': {
        'active_card': '무신사 현대카드 (3104)',
        'cost': 76300,
        'reward': 0,
        'points_used': 0,
        'hyundai': {'discount': 3815, 'remain': 23344, 'billed': 72485},
    },
    'tiles': [
        {'name': '무신사페이 × 농협카드', 'amount': 3000},
        {'name': '페이코', 'amount': 2000},
        {'name': '카카오페이 × BC카드', 'amount': 6000},
        {'name': '토스페이 × 삼성카드', 'amount': 5000},
        {'name': '무신사페이 × 하나카드', 'amount': 4000},
        {'name': 'KB Pay', 'amount': 4000},
    ],
}


def test_현대카드_한도가_남으면_청구예상으로_고른다():
    c = hyundai_choice(INFO)
    assert c is not None
    assert c['card'] == '무신사 현대카드'
    assert c['paid'] == 76300
    assert c['paid'] - c['billed_discount'] == 72485  # 사용자: 청구 예상 72,485 로 기록
    assert '23,344' in c['why']


def test_현대카드_한도가_끝나면_고르지_않는다():
    info = {**INFO, 'pay': {**INFO['pay'], 'hyundai': {'discount': 0, 'remain': 0, 'billed': None}}}
    assert hyundai_choice(info) is None


def test_기본카드가_현대가_아니면_청구할인을_믿지_않는다():
    info = {**INFO, 'pay': {**INFO['pay'], 'active_card': 'NH카드 (275*)'}}
    assert hyundai_choice(info) is None


def test_화면_청구예상이_다르면_화면값을_쓴다():
    info = {**INFO, 'pay': {**INFO['pay'], 'hyundai': {'discount': 3815, 'remain': 1, 'billed': 73000}}}
    c = hyundai_choice(info)
    assert c is not None and c['paid'] - c['billed_discount'] == 73000


def test_농협_타일_판별():
    assert is_nh_tile('무신사페이 × 농협카드')
    assert is_nh_tile('무신사페이 x NH카드')
    assert not is_nh_tile('무신사페이 × 하나카드')
    assert not is_nh_tile('카카오페이 × 농협카드')


def test_카드_글자_정리():
    assert clean_pay_card('NH카드 (275*) 할인 적용 중') == 'NH카드'
    assert clean_pay_card('무신사 현대카드 (3104)') == '무신사 현대카드'


def test_다른_수단_타일은_고른_혜택보다_큰_것만_큰_순서로():
    names = [t['name'] for t in other_tiles_over(INFO['tiles'], 3815)]
    assert names == ['카카오페이 × BC카드', '토스페이 × 삼성카드', 'KB Pay']  # 무신사페이 타일·페이코 2,000 은 뺀다


def test_무신사_현대카드에는_일반_현대_계수를_곱하지_않는다():
    assert billing_factor('무신사 현대카드') == 1.0
    assert billing_factor('현대카드') == 0.973


def test_탭_없음_판별():
    assert order_tab_gone('not found: no tab or popup with id 6a7f')
    assert not order_tab_gone('ok: now working in tab 960553ed')


def test_무신사는_결제_규칙이_켜져_있다():
    assert default_sources().by_id('MUSINSA').pay_rule


def test_기록_메모에_카드와_청구할인이_보인다():
    from samba_agent.agents.contracts import Assignment

    a = Assignment.model_construct(
        handoff={'card': '무신사페이', 'pay_card_name': 'NH카드', 'paid': 73300},
        options={},
    )
    note = wave_notes(a, {'account': 'buy-1', 'real_price': 73300})
    assert '무신사페이/NH카드' in note
    b = Assignment.model_construct(
        handoff={'card': '무신사페이', 'pay_card_name': '무신사 현대카드', 'paid': 76300, 'billed_discount': 3815},
        options={},
    )
    assert '청구할인 3,815원' in wave_notes(b, {'account': 'buy-1', 'real_price': 72485})


# ── 탭 소실 → 구매 재구성 → 승인 원가 안이면 결제 ──

ORDER = OrderRef(order_no='A1', source='무신사', seller='신세계몰', sku='S1', qty=1)
CFG = {'configurable': {'thread_id': 'job:1'}}


@pytest.fixture()
def reg() -> Registry:
    return Registry.load(DEFAULT_ROOT)


def _agents(log: list[str], costs: list[float], pay_results: list[AgentResult]):
    def buyer(_a):
        cost = costs.pop(0)
        log.append(f'buy:{cost:.0f}')
        return AgentResult(status='ok', reason='ok', payload={'account': 'buy-1', 'card': '무신사페이', 'cost': cost, 'margin_pct': 9.0})

    def payer(_a):
        r = pay_results.pop(0)
        log.append(f'pay:{r.status}')
        return r

    def ok(name):
        def fn(_a):
            log.append(name)
            return AgentResult(status='ok', reason='ok', payload={})

        return fn

    return {'buyer.musinsa': buyer, 'payer': payer, 'recorder': ok('record'), 'verifier': ok('verify')}


GONE = AgentResult(status='needs_human', reason='탭 닫힘', fail_reason=FailReason.ORDER_FORM_GONE)
PAID = AgentResult(status='ok', reason='결제 완료', payload={'paid': True})


def _run(reg, log, costs, pays):
    g = build_supervisor(reg, _agents(log, costs, pays), checkpointer=MemorySaver(), gate=True)
    g.invoke({'order': ORDER, 'options': {}, 'job_id': 1, 'dry_run': True}, CFG)
    return g.invoke(Command(resume={'approved': True, 'by': 'U1'}), CFG)


def test_탭이_닫히면_다시_만들어_같은_원가면_결제한다(reg):
    log: list[str] = []
    out = _run(reg, log, [74240, 74240], [GONE, PAID])
    assert log == ['buy:74240', 'pay:needs_human', 'buy:74240', 'pay:ok', 'record', 'verify']
    assert out['outcome'] == 'done'


def test_다시_만든_원가가_더_싸도_결제한다(reg):
    log: list[str] = []
    out = _run(reg, log, [74240, 72485], [GONE, PAID])
    assert out['outcome'] == 'done'


def test_다시_만든_원가가_비싸면_결제하지_않는다(reg):
    log: list[str] = []
    out = _run(reg, log, [72485, 76300], [GONE])
    assert log == ['buy:72485', 'pay:needs_human', 'buy:76300']
    assert out['outcome'] == 'needs_human'
    assert out['fail_reason'] is FailReason.COST_CHANGED


def test_두_번째_탭_소실은_사람에게(reg):
    log: list[str] = []
    out = _run(reg, log, [74240, 74240], [GONE, GONE])
    assert log == ['buy:74240', 'pay:needs_human', 'buy:74240', 'pay:needs_human']
    assert out['outcome'] == 'needs_human'


# ── 구매 단계: 주문서 견적 → 규칙 선택(respx 로 브릿지 목) ──
import json as _json

import httpx
import respx

from samba_agent.agents.base import AgentFailure
from samba_agent.agents.buyer import BuyerAgent
from samba_agent.agents.contracts import Assignment
from samba_agent.bridge.client import BridgeClient

URL = 'http://127.0.0.1:47811'


def _page(text: str) -> httpx.Response:
    return httpx.Response(200, json={'ok': True, 'result': text, 'steps': []})


@pytest.fixture()
def musinsa(monkeypatch) -> BuyerAgent:
    spec = Registry.load(DEFAULT_ROOT)['buyer.musinsa']
    agent = BuyerAgent(spec, BridgeClient(URL, 'a' * 64, allowed=spec.tools, busy_wait_s=0.0), lambda p, m: None)  # type: ignore[arg-type,return-value]
    agent._dry_run = False
    agent.evidence = []
    agent._quote_errors = []
    monkeypatch.setattr(BuyerAgent, '_payable_providers', lambda self, acc: {'site', 'musinsapay'})
    monkeypatch.setattr(BuyerAgent, '_allowed_providers', lambda self, acc=None: {'site', 'musinsapay'})
    return agent


def _mock(read: dict[str, object], tiles: dict[str, dict[str, object]], calls: list) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = _json.loads(request.content)['args']
        name, args = body['name'], _json.loads(body.get('args') or '{}')
        calls.append((name, args))
        if name == 'musinsa_pay_rule' and args.get('mode') == 'read':
            return _page(_json.dumps(read, ensure_ascii=False))
        if name == 'musinsa_pay_rule' and args.get('mode') == 'tile':
            return _page(_json.dumps(tiles.get(args['tile'], {'ok': True, 'usable': False}), ensure_ascii=False))
        raise AssertionError(f'예상치 못한 run_script: {name} {args}')

    respx.post(f'{URL}/tool/run_script').mock(side_effect=handler)
    respx.post(f'{URL}/tool/progress').mock(return_value=_page('ok'))
    respx.post(f'{URL}/tool/switch_tab').mock(return_value=_page('ok'))


def _a() -> Assignment:
    order = OrderRef(order_no='O1', source='MUSINSA', seller='신세계몰', sku='후드 집업', option='S')
    return Assignment(order=order, allowed_tools=('run_script', 'progress', 'switch_tab'), rules='', dry_run=False)


def _snap() -> dict[str, object]:
    return {'cost': 76300, 'points_used': 0, 'order_tab': 'T1', 'methods': ['무신사머니', '무신사페이', '토스페이', '카카오페이', '페이코']}


@respx.mock
def test_구매_현대카드_한도가_있으면_청구예상_원가(musinsa) -> None:
    calls: list = []
    _mock(INFO, {}, calls)  # 폰 타일은 모두 적용 안 됨
    snap = _snap()
    musinsa._apply_payment_quotes(_a(), 'buy-1', snap)
    assert (snap['pay_method'], snap['pay_card_name'], snap['cost'], snap['billed_discount']) == ('무신사페이', '무신사 현대카드', 72485, 3815)
    assert snap.get('pay_tile') is None
    tried = [args['tile'] for name, args in calls if args.get('mode') == 'tile']
    assert tried == ['카카오페이 × BC카드', '토스페이 × 삼성카드', 'KB Pay']  # 농협은 시험하지 않는다(현대 우선)


@respx.mock
def test_구매_현대_한도가_없으면_농협_즉시할인(musinsa) -> None:
    calls: list = []
    read = {**INFO, 'pay': {**INFO['pay'], 'hyundai': {'discount': 0, 'remain': 0, 'billed': None}}}
    nh = {'ok': True, 'usable': True, 'method': '무신사페이', 'card': 'NH카드 (275*)', 'cost': 73300, 'reward': 0, 'applied': True}
    _mock(read, {'무신사페이 × 농협카드': nh}, calls)
    snap = _snap()
    musinsa._apply_payment_quotes(_a(), 'buy-1', snap)
    assert (snap['pay_card_name'], snap['pay_tile'], snap['cost'], snap['pay_amount']) == ('NH카드', '무신사페이 × 농협카드', 73300, 73300)
    assert snap.get('billed_discount') == 0.0


@respx.mock
def test_구매_폰결제_할인이_실제로_더_크면_멈춘다(musinsa) -> None:
    calls: list = []
    kakao = {'ok': True, 'usable': True, 'method': '카카오페이', 'cost': 70300, 'applied': False}
    _mock(INFO, {'카카오페이 × BC카드': kakao}, calls)
    with pytest.raises(AgentFailure) as e:
        musinsa._apply_payment_quotes(_a(), 'buy-1', _snap())
    assert e.value.fail_reason is FailReason.PAY_RULE_STOP
    assert '카카오페이 × BC카드' in e.value.reason and '6,000' in e.value.reason


def test_머니_잔액이_모자라면_머니로_고르지_않는다():
    from samba_agent.agents.buyer import money_choice

    assert money_choice({'money': {'cost': 76300, 'balance': 197625, 'reward': 0}})['method'] == '무신사머니'
    assert money_choice({'money': {'cost': 76300, 'balance': 50000, 'reward': 0}}) is None


@respx.mock
def test_구매_현대_한도도_농협도_없으면_기본_무신사머니(musinsa) -> None:
    calls: list = []
    read = {**INFO, 'pay': {**INFO['pay'], 'hyundai': {'discount': 0, 'remain': 0, 'billed': None}}}
    read = {**read, 'tiles': [t for t in INFO['tiles'] if '농협' not in t['name']]}
    _mock(read, {}, calls)
    snap = _snap()
    musinsa._apply_payment_quotes(_a(), 'buy-1', snap)
    assert (snap['pay_method'], snap['pay_card'], snap['cost']) == ('무신사머니', None, 76300)
    assert not snap.get('pay_card_name') and not snap.get('pay_tile')


@respx.mock
def test_구매_농협_할인이_적용_안_되면_무신사머니(musinsa) -> None:
    calls: list = []
    read = {**INFO, 'pay': {**INFO['pay'], 'hyundai': {'discount': 0, 'remain': 0, 'billed': None}}}
    _mock(read, {'무신사페이 × 농협카드': {'ok': True, 'usable': False, 'method': '무신사페이'}}, calls)
    snap = _snap()
    musinsa._apply_payment_quotes(_a(), 'buy-1', snap)
    assert snap['pay_method'] == '무신사머니'


def test_페이코_타일은_정지_비교에서_뺀다():
    names = [t['name'] for t in other_tiles_over(INFO['tiles'], 0)]
    assert '페이코' not in names and '카카오페이 × BC카드' in names


def test_결제_전부터_있던_주문완료_탭은_이미_결제로_보지_않는다():
    import json as j

    from samba_agent.agents.payer import drop_tabs, looks_already_paid

    tabs = j.dumps([{'id': 'old', 'url': 'https://www.musinsa.com/order/order-complete/123'}, {'id': 'of', 'url': 'https://www.musinsa.com/order/order-form'}])
    assert looks_already_paid(tabs, '', 'musinsa.com')
    assert not looks_already_paid(drop_tabs(tabs, {'old'}), '', 'musinsa.com')


def test_검증도_청구할인_원가로_계산한다():
    from samba_agent.agents.source_detail import billed_cost

    detail = {'paid': 76300, 'reward': 0, 'points_used': 0, 'card': '현대카드'}
    assert billed_cost(detail, {'billed_discount': 3815}) == 72485
    assert billed_cost(detail, {}) == 74240  # 청구할인 없으면 예전 계산(현대 ×0.973)


@respx.mock
def test_구매_현대카드_원가는_적립_예정을_빼지_않은_청구예상(musinsa) -> None:
    # 실기 2026-10-12 반스 보트슈즈: 결제 63,200 · 청구할인 3,160 · 구매 적립 2,520 → 원가 60,040(적립 빼면 57,520 로 틀림)
    calls: list = []
    read = {**INFO, 'base_cost': 63200, 'pay': {**INFO['pay'], 'cost': 63200, 'reward': 2520, 'hyundai': {'discount': 3160, 'remain': 20184, 'billed': 60040}}}
    _mock(read, {}, calls)
    snap = _snap()
    musinsa._apply_payment_quotes(_a(), 'buy-1', snap)
    assert snap['cost'] == 60040


def test_지난_작업의_승인은_새_작업에_쓰지_않는다():
    from samba_agent.gateway.wave_approval import approval_older_than_job
    from samba_agent.queue.db import Job

    job = Job(id=1, order_no='O1', requester='intake', options={}, state='needs_human', assignee_agent=None, step='승인 대기: pay', thread_ts=None, harness_version=None, attempts=0, error=None, created_at='2026-10-12T14:10:00+00:00', updated_at='2026-10-12T14:11:00+00:00')
    assert approval_older_than_job({'state': 'approved', 'requested_at': '2026-10-12T13:50:00+00:00'}, job)
    assert not approval_older_than_job({'state': 'pending', 'requested_at': '2026-10-12T14:11:01+00:00'}, job)
    assert not approval_older_than_job({'state': 'approved'}, job)  # 시각 모르면 예전처럼


def test_원가가_오르면_새_원가로_다시_준비한다(reg):
    log: list[str] = []
    out = _run(reg, log, [72485, 76300], [GONE])
    assert out['fail_reason'] is FailReason.COST_CHANGED


def test_결제_전부터_떠_있던_완료화면_주소는_주문번호에서_뺀다():
    import json as j

    from samba_agent.agents.payer import _source_order_no, drop_urls

    old = 'https://www.musinsa.com/order/result/202610130012000002'
    tabs = j.dumps([{'id': 'a', 'url': old}])
    assert _source_order_no('', tabs) == '202610130012000002'
    assert _source_order_no('', drop_urls(tabs, {old})) is None


def test_결제창_즉시할인_종료_안내를_알아본다(tmp_path, monkeypatch):
    from samba_agent.agents import payer as pm

    page = '즉시할인 프로모션이 종료됐어요. 프로모션 예산이 조기 소진되어 즉시할인이 적용되지 않습니다. 할인 없이 결제하시겠어요? 취소 결제하기'
    assert pm.promo_ended(page)
    assert not pm.promo_ended('무신사페이 결제 73,300원 결제하기')
    monkeypatch.chdir(tmp_path)
    assert not pm.nh_promo_ended_today()
    pm.mark_nh_promo_ended()
    assert pm.nh_promo_ended_today()


@respx.mock
def test_구매_농협_예산_소진_표시가_있으면_무신사머니(musinsa, tmp_path, monkeypatch) -> None:
    from samba_agent.agents import payer as pm

    monkeypatch.chdir(tmp_path)
    pm.mark_nh_promo_ended()
    calls: list = []
    read = {**INFO, 'pay': {**INFO['pay'], 'hyundai': {'discount': 0, 'remain': 0, 'billed': None}}}
    _mock(read, {'무신사페이 × 농협카드': {'ok': True, 'usable': True, 'method': '무신사페이', 'card': 'NH카드', 'cost': 73300}}, calls)
    snap = _snap()
    musinsa._apply_payment_quotes(_a(), 'buy-1', snap)
    assert snap['pay_method'] == '무신사머니'
    assert not any(args.get('tile') == '무신사페이 × 농협카드' for _, args in calls)
