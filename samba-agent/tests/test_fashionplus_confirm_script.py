"""패션플러스 배송지 확정 스크립트(site-scripts/fashionplus_confirm_shipping.js)를 가짜 화면으로 돌려 본다.

실기 2026-10-22~23: 확정 5건이 모두 등록하기 뒤 창이 안 닫힌 채 33초를 기다리고 주문서의 옛 배송지를 되읽어
'넣은 값과 다르다'로 끝났다. 창이 그대로인지·목록으로 돌아갔는지·주문서가 바뀌었는지를 나눠 돌려주는지 본다.
node 가 없으면 건너뛴다.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / 'site-scripts'
NODE = shutil.which('node')
pytestmark = pytest.mark.skipif(NODE is None, reason='node 없음')

# 가짜 앱: page.get 은 상태(state)에 따라 트리를 만든다. 등록하기 클릭이 상태를 바꾼다
RUNNER = r"""
const fs = require('fs')
const [file, scenario, argsJson] = process.argv.slice(2)
const args = JSON.parse(argsJson)
const ORDER = 'https://www.fashionplus.co.kr/order/87654321'
const st = { form: true, list: false, sheet: '김옛날배송지 변경 04524 서울 중구 세종대로 110 01011112222', clicks: [] }
const NEW = '홍길동배송지 변경 05300 서울 강동구 천중로35길 6-1 401호 01000000000'
const form = () => [
  '[1000002] textbox "이름" value="홍길동"',
  '[1000004] textbox "휴대폰" value="01000000000"',
  '[1000006] textbox "우편번호" value="05300"',
  '[1000007] link "우편번호 찾기"',
  '[1000009] textbox "주소" value="서울 강동구 천중로35길 6-1"',
  '[1000010] textbox "상세주소" value="401호"',
  '[1000012] button "등록하기"',
]
const list = () => [
  '[1000020] link "배송지 선택"',
  '[1000021] link "새 주소 입력"',
  '[1000022] link "김옛날 01011112222 04524 서울 중구 세종대로 110"',
  '[1000023] link "홍길동 01000000000 05300 서울 강동구 천중로35길 6-1 401호"',
]
const tree = () => {
  const ls = ['[12] link "배송지 변경"']
  if (st.form) ls.push(...form())
  if (st.list) ls.push(...list())
  if (st.layer) ls.unshift('[1000030] button "확인"')
  const head = st.overlay ? 'OVERLAY: "상세주소를 입력해 주세요" is covering the page - close ids: [1000031]\n' : ''
  return head + ls.join('\n') + '\nPAGE TEXT: 주문서 배송지 정보 ' + st.sheet + ' 배송메모'
}
const page = {
  get: async () => ({ tree: tree() }),
  type: async () => 'ok',
  click: async id => {
    st.clicks.push(id)
    if (id === 1000012) {
      if (scenario === 'applied') { st.form = false; st.sheet = NEW }
      if (scenario === 'to_list') { st.form = false; st.list = true }
      if (scenario === 'stuck') { st.overlay = true }
    }
    if (id === 1000031) st.overlay = false
    if (id === 1000023) { st.list = false; st.sheet = NEW }
    return 'ok'
  },
}
const tabs = { list: async () => [{ id: 't1', url: ORDER, kind: 'tab' }], switch: async () => 'ok' }
const sleep = async () => {}
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor
new AsyncFunction('page', 'tabs', 'args', 'sleep', fs.readFileSync(file, 'utf8'))(page, tabs, args, sleep)
  .then(r => console.log(JSON.stringify({ r, clicks: st.clicks })))
"""

ARGS = {
    'name': '홍길동',
    'address': '서울 강동구 천중로35길 6-1',
    'address_detail': '401호',
    'tab': 't1',
    'name_id': 1000002,
    'phone_id': 1000004,
    'zip_id': 1000006,
    'road_id': 1000009,
    'detail_id': 1000010,
}


def _run(tmp_path: Path, scenario: str) -> dict[str, object]:
    runner = tmp_path / 'runner.js'
    runner.write_text(RUNNER, encoding='utf-8')
    out = subprocess.run(
        [
            str(NODE),
            str(runner),
            str(SCRIPTS / 'fashionplus_confirm_shipping.js'),
            scenario,
            json.dumps(ARGS),
        ],
        capture_output=True,
        text=True,
        encoding='utf-8',
        timeout=30,
        check=True,
    )
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_등록하기로_주문서가_바뀌면_통과한다(tmp_path: Path) -> None:
    got = _run(tmp_path, 'applied')
    r = got['r']
    assert r['ok'] is True and r['name'] == '홍길동' and r['zip'] == '05300'


def test_창이_목록으로_돌아가면_새_항목을_골라_통과한다(tmp_path: Path) -> None:
    got = _run(tmp_path, 'to_list')
    assert 1000023 in got['clicks']
    assert got['r']['ok'] is True


def test_창이_안_닫히면_사이트_안내를_사유로_남긴다(tmp_path: Path) -> None:
    got = _run(tmp_path, 'stuck')
    r = got['r']
    assert r['ok'] is False
    assert r['note'].startswith('등록하기 뒤 창이 안 닫힘')
    assert '상세주소를 입력해 주세요' in r['note']
    # 예전 사유('넣은 값과 다르다')로 뭉개지 않는다 — 옛 배송지를 새 배송지로 착각하지 않는다
    assert '넣은 값과 다르다' not in r['note']
