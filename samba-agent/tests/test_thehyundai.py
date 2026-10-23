"""더현대Hi 자동결제 합류(2026-10-23) — 소싱처 표·결제수단(현대백화점카드 간편결제 = 키마스터 site)·업무폰·스크립트 묶음."""

import json
import re
from pathlib import Path

import pytest

from samba_agent.agents.buyer import (
    _CLOSE_ORDER_TABS_JS,
    BuyerAgent,
    method_providers,
    product_no_of,
    quote_provider,
    snapshot_args,
)
from samba_agent.agents.contracts import OrderRef
from samba_agent.agents.payer import _pay_provider, checkout_script_for, web_pay_provider
from samba_agent.agents.registry import Registry
from samba_agent.agents.source_detail import billed_cost, detail_script
from samba_agent.bridge.client import BridgeClient
from samba_agent.settings import DEFAULT_ROOT
from samba_agent.sources import Sources

URL = 'http://127.0.0.1:47811'
PRODUCT = 'https://hi.thehyundai.com/product/40B0696270'
CARD = '현대백화점카드 간편결제'
SCRIPTS = (
    'thehyundai_product_snapshot',
    'thehyundai_set_shipping',
    'thehyundai_confirm_shipping',
    'checkout_enter_thehyundai',
    'thehyundai_order_detail',
)
BUNDLE = Path(DEFAULT_ROOT) / 'site-scripts'


def _order(**kw: object) -> OrderRef:
    row = {'order_no': 'A1', 'source': 'THEHYUNDAI', 'seller': '신세계몰', 'sku': 'x', 'qty': 1}
    return OrderRef.model_validate(row | kw)


@pytest.fixture()
def buyer() -> BuyerAgent:
    reg = Registry.load(DEFAULT_ROOT)
    spec = reg['buyer.thehyundai']
    agent = BuyerAgent(
        spec,
        BridgeClient(URL, 'a' * 64, allowed=spec.tools, busy_wait_s=0.0),
        lambda p, m: None,  # type: ignore[arg-type,return-value]
    )
    agent.evidence = []
    return agent


def test_더현대_행은_직배_업무폰_현대백화점카드_원가실결제() -> None:
    row = Sources.load(DEFAULT_ROOT).by_id('THEHYUNDAI')  # 삼바웨이브 source_site 표기(대문자)
    assert row is not None and row.id == 'TheHyundai' and row.key == 'thehyundai'
    assert row.status == 'active'
    assert row.order_type == 'direct'
    # 배송 연락처 = 사장님 CS 번호(키마스터 신원정보) — 고객 번호 안 씀
    assert row.customer_phone is False
    assert row.shipping_confirm is True and row.reuse_saved_shipping is False
    # 결제 = 현대백화점카드 간편결제 하나(키마스터 결제 비밀번호 제공자 site)
    assert row.pay_provider == 'site'
    assert row.paid_is_cost is True
    assert row.buy_accounts == ['buy-1']
    assert row.login_host == 'thehyundai.com'
    assert row.snapshot_script == 'thehyundai_product_snapshot'
    assert row.checkout_script_name == 'checkout_enter_thehyundai'
    assert row.confirm_shipping_script == 'thehyundai_confirm_shipping'


def test_등록부에_더현대_구매_에이전트가_생기고_규칙파일을_쓴다() -> None:
    reg = Registry.load(DEFAULT_ROOT)
    assert 'buyer.thehyundai' in reg.names()
    assert reg['buyer.thehyundai'].rules == 'rules/buyer_thehyundai.md'
    assert reg.pick('buyer', _order(), {}) is not None


def test_스냅샷_sku_는_slitmCd_다() -> None:
    args = json.loads(snapshot_args('buyer.thehyundai', _order(product_url=PRODUCT + '?a=1', option='240')))
    assert args['sku'] == '40B0696270' and args['size'] == '240'


def test_상품번호는_영숫자_slitmCd_다() -> None:
    assert product_no_of(PRODUCT) == '40B0696270'
    assert product_no_of('https://hi.thehyundai.com/product/2246940700?x=1') == '2246940700'
    # 기존 규칙은 그대로
    assert product_no_of('https://www.musinsa.com/products/5837910') == '5837910'
    assert product_no_of('https://www.fashionplus.co.kr/goods/detail/12345678') == '12345678'


def test_현대백화점카드_간편결제는_사이트_결제비밀번호_웹키패드다() -> None:
    assert quote_provider(CARD) == 'site'
    assert method_providers(CARD) == {'site'}
    # 결제 단계: 폰 결제 앱이 아니다(웹 키패드) · 키마스터 결제 비밀번호 제공자 site
    assert _pay_provider(CARD) is None
    assert web_pay_provider(CARD) == 'site'


def test_더현대는_허용수단이_site_하나다(buyer: BuyerAgent) -> None:
    buyer.allowed_pay_providers = {'musinsapay', 'naver'}  # 전역 허용 수단과 무관하게 소싱처 고정이 이긴다
    assert buyer._allowed_providers('buy-1') == {'site'}


def test_원가는_실결제액이다_현대카드_계수를_안_곱한다() -> None:
    detail = {'paid': 100000, 'card': '현대백화점카드', 'points_used': 0, 'reward': 0}
    assert billed_cost(detail, {'paid_is_cost': True}) == 100000


def test_결제창_진입과_주문상세_스크립트_이름() -> None:
    assert checkout_script_for('THEHYUNDAI') == 'checkout_enter_thehyundai'
    assert checkout_script_for('더현대닷컴') == 'checkout_enter_thehyundai'
    assert detail_script('THEHYUNDAI') == 'thehyundai_order_detail'


def test_주문서_탭_닫기는_더현대_주문서만_닫고_마이페이지는_둔다() -> None:
    js = re.search(r'if \(!t\.lane && /(.+?)/\.test', _CLOSE_ORDER_TABS_JS)
    assert js
    pat = re.compile(js.group(1).replace(r'\/', '/'))
    assert pat.search('https://hi.thehyundai.com/order/orderSheet?x=1')
    assert not pat.search(PRODUCT)
    assert not pat.search('https://hi.thehyundai.com/mypage/order/list')


@pytest.mark.parametrize('name', SCRIPTS)
def test_스크립트_묶음에_있고_앱_저장_규칙을_지킨다(name: str) -> None:
    index = {e['name']: e for e in json.loads((BUNDLE / 'index.json').read_text(encoding='utf-8'))}
    assert name in index and index[name]['host'] == 'thehyundai.com'
    assert len(index[name]['description']) <= 240
    code = (BUNDLE / f'{name}.js').read_text(encoding='utf-8')
    # 앱 save_script 규칙: 8000자 이하, 긴 숫자(주문번호 같은 9자리 이상) 없음, args 를 읽는다
    assert len(code) <= 8000
    assert not re.search(r'\d{9,}', code)
    assert 'args' in code
    # 비밀값을 스크립트가 다루지 않는다 — 결제 비밀번호·전화번호는 앱(fill_secret)이 넣는다
    assert 'fill_secret' not in code and 'password' not in code.lower()


def test_결제창_진입은_현대백화점카드가_아니면_누르지_않는다() -> None:
    code = (BUNDLE / 'checkout_enter_thehyundai.js').read_text(encoding='utf-8')
    assert "if (!/현대백화점/.test(card)) return fail('unknown pay method" in code
    # 실결제 안전장치(dryRun·expect·amount·tab)
    for guard in ("fail('no expect')", "fail('no amount')", "fail('no tab')", 'dryRun: 결제하기 전 멈춤'):
        assert guard in code


def test_배송지_입력은_전화번호를_넣지_않고_칸_번호만_돌려준다() -> None:
    code = (BUNDLE / 'thehyundai_set_shipping.js').read_text(encoding='utf-8')
    assert 'phone_field_id' in code
    assert 'A.phone' not in code and 'args.phone' not in code
