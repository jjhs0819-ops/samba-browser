"""패션플러스 새 배송지 등록 동안 적립금 해제 → 배송지 확정 뒤 다시 적용(2026-10-27).

실기 2026-10-27: 적립금 7,550원을 쓴 주문서에서 새 배송지 5건이 모두 실패했다('등록하기 뒤 창이 안 닫힘(안내: 적립금
7,550 원을 사용 합니다.)' 3건, '주소가 폼에 안 들어감' 2건). 적립금 0원 주문서의 새 배송지는 통과했다.
하네스 순서(정리 → 해제 → 입력 → 확정 → 재적용)와 재적용 대조, 해제 스크립트(가짜 화면)를 본다.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from samba_agent.agents.base import AgentFailure
from samba_agent.agents.buyer import BuyerAgent
from samba_agent.agents.contracts import Assignment, OrderRef
from samba_agent.agents.registry import Registry
from samba_agent.bridge.client import BridgeClient
from samba_agent.settings import DEFAULT_ROOT

URL = 'http://127.0.0.1:47811'
SHIP = {'name': '홍길동', 'address': '서울 강동구 천중로35길 6-1', 'phone': '01000000000'}
APPLIED = {
    'ok': True,
    'name': '홍길동',
    'address': '서울 강동구 천중로35길 6-1',
    'phone_field_id': 1000004,
    'name_field_id': 1000002,
    'zip_field_id': 1000006,
    'road_field_id': 1000009,
    'detail_field_id': 1000010,
}


@pytest.fixture
def buyer(monkeypatch) -> BuyerAgent:
    spec = Registry.load(DEFAULT_ROOT)['buyer.fashionplus']
    agent = BuyerAgent(
        spec,
        BridgeClient(URL, 'a' * 64, allowed=spec.tools, busy_wait_s=0.0),
        lambda p, m: None,  # type: ignore[arg-type,return-value]
    )
    agent._dry_run = False
    agent.evidence = []
    monkeypatch.setattr(BuyerAgent, '_fill_phone', lambda self, applied, phone=None: None)
    monkeypatch.setattr(
        BuyerAgent,
        'script_json',
        lambda self, name, args, **kw: (
            dict(APPLIED)
            if name.endswith('_set_shipping')
            else {'ok': True, 'name': SHIP['name'], 'address': SHIP['address']}
        ),
    )
    return agent


def _assignment(buyer: BuyerAgent) -> Assignment:
    order = OrderRef(
        order_no='A1',
        source='FashionPlus',
        seller='포이즌',
        sku='12345678',
        qty=1,
        option='BLACK 250',
    )
    return Assignment(order=order, allowed_tools=buyer.spec.tools, rules='', dry_run=False)


def _fake_tools(monkeypatch, release: dict[str, object], prep: dict[str, object]) -> list[str]:
    calls: list[str] = []

    def json_tool(self, tool, **kw):
        name = str(kw.get('name'))
        calls.append(name)
        if name.endswith('_address_prune'):
            return {'ok': True, 'deleted': 0, 'left': 0}
        if name.endswith('_points_release'):
            return dict(release)
        if name.endswith('_order_prep'):
            return dict(prep)
        raise AssertionError(name)

    monkeypatch.setattr(BuyerAgent, 'json_tool', json_tool)
    return calls


def test_적립금을_풀고_등록한_뒤_같은_값으로_다시_적용한다(buyer, monkeypatch) -> None:
    calls = _fake_tools(
        monkeypatch,
        {'ok': True, 'used_before': 7550, 'total_before': 61520, 'used': 0, 'total': 69070},
        {'ok': True, 'points_used': 7550, 'total': 61520},
    )
    buyer._apply_shipping(_assignment(buyer), dict(SHIP), 'buy-1')
    assert calls == [
        'fashionplus_address_prune',
        'fashionplus_points_release',
        'fashionplus_order_prep',
    ]
    assert any('다시 사용' in e.detail for e in buyer.evidence)


def test_재적용_뒤_결제액이_다르면_결제하지_않는다(buyer, monkeypatch) -> None:
    # 도서산간 배송비 5,000원이 붙은 경우 — 견적·원가와 어긋난다
    _fake_tools(
        monkeypatch,
        {'ok': True, 'used_before': 7550, 'total_before': 61520, 'used': 0, 'total': 69070},
        {'ok': True, 'points_used': 7550, 'total': 66520},
    )
    with pytest.raises(AgentFailure) as e:
        buyer._apply_shipping(_assignment(buyer), dict(SHIP), 'buy-1')
    assert e.value.status == 'needs_human'
    assert '결제하지 않음' in e.value.reason


def test_쓰던_적립금이_없으면_다시_적용하지_않는다(buyer, monkeypatch) -> None:
    calls = _fake_tools(
        monkeypatch,
        {'ok': True, 'used_before': 0, 'total_before': 69070, 'used': 0, 'total': 69070},
        {'ok': True, 'points_used': 0, 'total': 69070},
    )
    buyer._apply_shipping(_assignment(buyer), dict(SHIP), 'buy-1')
    assert 'fashionplus_order_prep' not in calls


# --- 해제 스크립트(site-scripts/fashionplus_points_release.js) — node 가 없으면 건너뛴다 ---
SCRIPTS = Path(__file__).resolve().parents[1] / 'site-scripts'
NODE = shutil.which('node')

RUNNER = r"""
const fs = require('fs')
const [file, scenario] = process.argv.slice(2)
const ORDER = 'https://www.fashionplus.co.kr/order/87654321'
const st = { on: scenario !== 'none', used: scenario === 'none' ? 0 : 7550, clicks: [], typed: [] }
const tree = () => [
  '[40] checkbox value="' + (st.on ? 'on' : 'off') + '"',
  '[41] clickable "적립금 모두사용"',
  '[42] textbox value="' + st.used + '"',
  '[43] button "적용"',
].join('\n') + '\nPAGE TEXT: 보유 적립금 7,550 적립금 사용액 - ' + st.used.toLocaleString() + ' 총 결제 예상금액 (1건) ' + (69070 - st.used).toLocaleString()
const page = {
  get: async () => ({ tree: tree() }),
  type: async (id, v) => { st.typed.push([id, v]); return 'ok' },
  click: async id => {
    st.clicks.push(id)
    // stuck: 체크를 꺼도 사용액이 남아 칸에 0을 넣고 적용해야 풀린다
    if (id === 41) { st.on = !st.on; if (scenario !== 'stuck') st.used = st.on ? 7550 : 0 }
    if (id === 43 && st.typed.length) st.used = 0
    return 'ok'
  },
}
const tabs = { list: async () => [{ id: 't1', url: ORDER, kind: 'tab' }], switch: async () => 'ok' }
const sleep = async () => {}
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor
new AsyncFunction('page', 'tabs', 'args', 'sleep', fs.readFileSync(file, 'utf8'))(page, tabs, { tab: 't1' }, sleep)
  .then(r => console.log(JSON.stringify({ r, clicks: st.clicks, typed: st.typed })))
"""


def _run(tmp_path: Path, scenario: str) -> dict[str, object]:
    runner = tmp_path / 'runner.js'
    runner.write_text(RUNNER, encoding='utf-8')
    out = subprocess.run(
        [str(NODE), str(runner), str(SCRIPTS / 'fashionplus_points_release.js'), scenario],
        capture_output=True,
        text=True,
        encoding='utf-8',
        timeout=30,
        check=True,
    )
    return json.loads(out.stdout.strip().splitlines()[-1])


@pytest.mark.skipif(NODE is None, reason='node 없음')
def test_해제_스크립트는_모두사용을_꺼서_0원으로_만든다(tmp_path: Path) -> None:
    got = _run(tmp_path, 'on')
    r = got['r']
    assert r['ok'] is True and r['used'] == 0
    assert (r['used_before'], r['total_before']) == (7550, 61520)
    assert got['clicks'] == [41]


@pytest.mark.skipif(NODE is None, reason='node 없음')
def test_체크를_꺼도_남으면_칸에_0을_넣고_적용한다(tmp_path: Path) -> None:
    got = _run(tmp_path, 'stuck')
    assert got['r']['ok'] is True
    assert got['typed'] == [[42, '0']] and 43 in got['clicks']


@pytest.mark.skipif(NODE is None, reason='node 없음')
def test_쓰던_적립금이_없으면_아무것도_누르지_않는다(tmp_path: Path) -> None:
    got = _run(tmp_path, 'none')
    assert got['r']['ok'] is True and got['r']['used_before'] == 0
    assert got['clicks'] == []
