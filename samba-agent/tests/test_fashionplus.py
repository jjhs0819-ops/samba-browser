"""패션플러스 주문 이행 연동(2026-09-27) — 소싱처 표·주문서 탭 정리·상품번호·상품 전체 품절(SOLD OUT) 확정."""

import re

import pytest

from samba_agent.agents.base import AgentFailure
from samba_agent.agents.buyer import (
    _CLOSE_ORDER_TABS_JS,
    CONFIRMED_SOLD_OUT,
    SOLD_OUT_PRODUCT_SKIP,
    BuyerAgent,
    is_confirmed_sold_out_skip,
    product_no_of,
    snapshot_args,
    snapshot_problem,
    snapshot_sold_out,
)
from samba_agent.agents.contracts import Assignment, OrderRef
from samba_agent.agents.registry import Registry
from samba_agent.bridge.client import BridgeClient
from samba_agent.failures import FailReason
from samba_agent.settings import DEFAULT_ROOT
from samba_agent.sources import Sources

URL = 'http://127.0.0.1:47811'
PRODUCT = 'https://www.fashionplus.co.kr/goods/detail/12345678'
ORDER_FORM = 'https://www.fashionplus.co.kr/order/87654321'
ACCOUNTS = ['buyer01', 'buyer02']
# 스냅샷 초안이 상품 전체 품절에 돌려주는 모양(선택지 0개·sold_out·error)
SOLD_SNAP: dict[str, object] = {
    'options': [],
    'sold_out': True,
    'error': 'sold_out',
    'note': '상품 전체 품절(SOLD OUT, 선택지 0개)',
    'cost': None,
    'methods': [],
    'selected': None,
}


def _close_re() -> re.Pattern[str]:
    r"""주문서 탭 닫기 JS 의 정규식을 파이썬으로 옮긴다(JS 의 '\/' 는 '/')."""
    js = re.search(r'if \((?:!t\.lane && )?/(.+?)/\.test', _CLOSE_ORDER_TABS_JS)
    assert js
    return re.compile(js.group(1).replace(r'\/', '/'))


def test_패션플러스_행은_네이버페이_정돈_배송확정_상품ID_를_켠다() -> None:
    fp = Sources.load(DEFAULT_ROOT).by_id('패션플러스')
    assert fp is not None and fp.id == 'FashionPlus'
    assert fp.pay_provider == 'naver'
    assert fp.order_prep and fp.shipping_confirm and fp.payment_quotes
    assert fp.order_prep_script == 'fashionplus_order_prep'
    assert fp.confirm_shipping_script == 'fashionplus_confirm_shipping'
    assert fp.checkout_script_name == 'checkout_enter_fashionplus'


def test_패션플러스_스냅샷_sku_는_상품번호다() -> None:
    order = OrderRef.model_validate(
        {
            'order_no': 'A1',
            'source': 'FashionPlus',
            'seller': '포이즌',
            'sku': 'x',
            'qty': 1,
            'product_url': PRODUCT + '?utm=1',
        }
    )
    assert '"sku": "12345678"' in snapshot_args('buyer.fashionplus', order)


def test_패션플러스_주문서_탭도_스냅샷_전에_닫는다() -> None:
    pat = _close_re()
    assert pat.search(ORDER_FORM)
    # 상품·주문 관리·주문 상세 탭은 닫지 않는다
    assert not pat.search(PRODUCT)
    assert not pat.search('https://www.fashionplus.co.kr/mypage/order')
    assert not pat.search('https://www.fashionplus.co.kr/mypage/order/detail/87654321')
    # 기존 사이트 주문서는 그대로 닫힌다
    assert pat.search('https://pay.ssg.com/order/ordPage.ssg?ordKey=1')


def test_패션플러스_상품번호는_goods_detail_이다() -> None:
    assert product_no_of(PRODUCT) == '12345678'
    assert product_no_of(PRODUCT + '?x=1') == '12345678'
    assert product_no_of('https://www.musinsa.com/products/5837910') == '5837910'


def test_상품_전체_품절은_sold_out_참이고_선택지가_없을_때만이다() -> None:
    assert snapshot_sold_out(SOLD_SNAP)
    # 선택지가 하나라도 읽혔으면 확증이 아니다
    assert not snapshot_sold_out({**SOLD_SNAP, 'options': ['BLACK / 250']})
    # 참 비슷한 값(문자열)은 받지 않는다
    assert not snapshot_sold_out({**SOLD_SNAP, 'sold_out': 'true'})
    assert not snapshot_sold_out({'options': [], 'note': 'no options'})


def test_상품_전체_품절이면_스냅샷_수리를_하지_않는다() -> None:
    assert snapshot_problem('BLACK 250')(SOLD_SNAP) is None
    assert snapshot_problem(None)(SOLD_SNAP) is None
    # 표시 없이 선택지만 비면 여전히 수리 대상
    assert snapshot_problem('BLACK 250')({'options': [], 'note': 'no options'}) is not None


def test_상품_전체_품절_사유는_확정_품절로_본다() -> None:
    assert is_confirmed_sold_out_skip(f'buyer01: {SOLD_OUT_PRODUCT_SKIP} (SOLD OUT)')


@pytest.fixture()
def buyer(monkeypatch) -> BuyerAgent:
    reg = Registry.load(DEFAULT_ROOT)
    spec = reg['buyer.fashionplus']
    agent = BuyerAgent(
        spec,
        BridgeClient(URL, 'a' * 64, allowed=spec.tools, busy_wait_s=0.0),
        lambda p, m: None,  # type: ignore[arg-type,return-value]
    )
    agent._dry_run = False
    agent.evidence = []
    agent._quote_errors = []
    agent._quote_skips = []
    cls = type(agent)
    monkeypatch.setattr(cls, '_payable_providers', lambda self, acc: None)
    monkeypatch.setattr(cls, '_allowed_providers', lambda self, acc=None: None)
    monkeypatch.setattr(cls, '_login_as', lambda self, acc: None)

    def no_ai(self: BuyerAgent, options: list[str], wanted: str | None) -> list[str]:
        raise AssertionError('상품 전체 품절에서 옵션 대조(AI 매칭)까지 가면 안 된다')

    monkeypatch.setattr(cls, '_match_options', no_ai)
    return agent


def _assignment(buyer: BuyerAgent) -> Assignment:
    order = OrderRef(
        order_no='A1',
        source='FashionPlus',
        seller='포이즌',
        sku='12345678',
        qty=1,
        option='BLACK 250',
        product_url=PRODUCT,
    )
    return Assignment(order=order, allowed_tools=buyer.spec.tools, rules='', dry_run=False)


def test_견적에서_상품_전체_품절은_옵션_대조_없이_확정_품절_사유로_남긴다(
    buyer, monkeypatch
) -> None:
    monkeypatch.setattr(BuyerAgent, '_snapshot', lambda self, a, acc: dict(SOLD_SNAP))
    assert buyer._quote(_assignment(buyer), 'buyer01') is None
    assert len(buyer._quote_skips) == 1
    assert is_confirmed_sold_out_skip(buyer._quote_skips[0])


def test_모든_계정이_상품_전체_품절이면_확정_품절로_끝난다(buyer, monkeypatch) -> None:
    monkeypatch.setattr(BuyerAgent, '_snapshot', lambda self, a, acc: dict(SOLD_SNAP))
    with pytest.raises(AgentFailure) as e:
        buyer._pick_cheapest(_assignment(buyer), ACCOUNTS)
    assert e.value.reason.startswith(CONFIRMED_SOLD_OUT)
    assert e.value.fail_reason is FailReason.OUT_OF_STOCK


def test_배송지_확정은_입력_스크립트가_채운_칸_번호로_되읽는다(buyer, monkeypatch) -> None:
    """실기 2026-10-22: 확정 스크립트가 칸을 순서로 추측해 3건 모두 '폼 이름이 다르다' — 입력이 돌려준 번호를 넘긴다."""
    ship = {'name': '홍길동', 'address': '서울 강동구 천중로35길 6-1', 'phone': '01000000000'}
    applied = {
        'ok': True,
        'name': '홍길동',
        'address': '서울 강동구 천중로35길 6-1',
        'phone_field_id': 1000004,
        'name_field_id': 1000002,
        'zip_field_id': 1000006,
        'road_field_id': 1000009,
        'detail_field_id': 1000010,
    }
    seen: list[dict[str, object]] = []

    def fake_script(self, name, args, **kw):
        seen.append({**args, 'script': name})
        return (
            applied
            if name.endswith('_set_shipping')
            else {'ok': True, 'name': ship['name'], 'address': ship['address']}
        )

    monkeypatch.setattr(BuyerAgent, 'script_json', fake_script)
    monkeypatch.setattr(BuyerAgent, '_fill_phone', lambda self, applied, phone=None: None)
    buyer._apply_shipping(_assignment(buyer), dict(ship), 'buyer01')
    confirm = next(s for s in seen if str(s['script']).endswith('_confirm_shipping'))
    assert (confirm['name_id'], confirm['phone_id'], confirm['zip_id'], confirm['road_id']) == (
        1000002,
        1000004,
        1000006,
        1000009,
    )
    assert 'phone' not in confirm
    # 상세주소 칸 번호도 넘긴다 — 확정 스크립트가 비어 있으면 다시 채운다(실기 2026-10-23 창이 안 닫힘)
    assert confirm['detail_id'] == 1000010


def test_스냅샷이_주문서를_못_열면_배송지로_넘어가지_않고_스냅샷_사유로_멈춘다(
    buyer, monkeypatch
) -> None:
    """실기 2026-10-23 11:00 패션플러스 2건: 옵션은 맞게 읽었는데 주문서를 못 열었고, 그대로 배송지로 넘어가
    '배송지 입력 검증에 실패했다: no order tab' 으로 엉뚱한 단계에서 멈췄다."""
    monkeypatch.setattr(
        BuyerAgent,
        '_match_options',
        lambda self, options, wanted: [o for o in options if o == wanted],
    )
    called: list[str] = []
    monkeypatch.setattr(
        BuyerAgent, '_set_shipping', lambda self, a, snap, acc: called.append('ship')
    )
    snap: dict[str, object] = {
        'options': ['BLACK 240', 'BLACK 250'],
        'selected': None,
        'cost': None,
        'methods': [],
        'note': 'buy: 구매할 상품을 선택해주세요',
    }
    with pytest.raises(AgentFailure) as e:
        buyer._buy_here(_assignment(buyer), ['buyer01'], 'buyer01', snap)
    assert called == []
    assert e.value.reason.startswith('주문서를 못 열었다')
    assert '구매할 상품을 선택해주세요' in e.value.reason
