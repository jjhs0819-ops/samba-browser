# 소싱처 자동취소 실행기 — 판정 순수함수 · 재확인(check→cancel) · 텔레그램 1통 규칙
from __future__ import annotations

import pytest

from samba_agent.failures import FailReason
from samba_agent.ops.source_cancel import (
    SourceCanceller,
    decide,
    order_no_token_match,
    resolve_profile,
)
from samba_agent.sources import Source, Sources, default_sources
from samba_agent.wave.client import RobotCancelItem, WaveError


def _item(**kw: object) -> RobotCancelItem:
    base = {
        'id': 'rc_1',
        'order_id': 'ord_1',
        'order_number': '20261028001',
        'source_site': 'MUSINSA',
        'sourcing_order_number': 'M20261028777',
        'account_username': 'buy-1',
        'mode': 'cancel',
        'bundle_count': 1,
    }
    return RobotCancelItem.model_validate({**base, **kw})


def _screen(**kw: object) -> dict[str, object]:
    base = {
        'source_order_no': 'M20261028777',
        'login': True,
        'found': True,
        'items': 1,
        'state': 'cancellable',
        'buttons': 1,
        'clicked': False,
        'after_state': '',
        'note': None,
    }
    return {**base, **kw}


def _sources() -> Sources:
    return Sources(
        [
            Source(id='MUSINSA', key='musinsa', label='무신사', buy_accounts=['buy-1']),
            # 검증 사이트(SITE_VERIFIED)인데 구매 계정이 2개 — 계정 결정 규칙 테스트용
            Source(id='LOTTEON', key='lotteon', label='롯데온', buy_accounts=['b1', 'b2']),
            # 실제 sources.yaml 처럼 buy_accounts 가 없다(DB source_site 는 THEHYUNDAI 로 온다)
            Source(id='TheHyundai', key='thehyundai', label='더현대닷컴'),
            Source(id='GrandStage', key='abc', label='그랜드', buy_accounts=['b1', 'b2']),
            Source(id='GSShop', key='gsshop', label='GS샵', buy_accounts=['g1']),
            Source(id='FashionPlus', key='fashionplus', label='패션플러스', buy_accounts=['f1']),
        ]
    )


# ---- decide: 규칙 7가지 ----


def test_decide_묶음은_화면을_보기_전에_bundle이다():
    assert decide(_item(bundle_count=2), None)[0] == 'bundle'
    assert decide(_item(bundle_count=3), _screen())[0] == 'bundle'


def test_decide_삼바_송장이나_배송상태가_발송이면_화면을_보기_전에_shipped다():
    # 통제자 판정(최종 리뷰): 삼바 데이터로 이미 발송이 확인되면 소싱처 화면을 열지 않는다
    reason = '삼바 송장/배송상태로 발송 확인'
    assert decide(_item(tracking_number='1234567890'), None) == ('shipped', reason)
    assert decide(_item(shipping_status='국내배송중'), None) == ('shipped', reason)
    assert decide(_item(shipping_status='송장전송완료'), _screen()) == ('shipped', reason)
    assert decide(_item(shipping_status='구매확정'), _screen()) == ('shipped', reason)
    # 부분 문자열 — 백엔드 SHIPPED_SHIPPING_STATUS_KEYWORDS 와 같은 규칙
    assert decide(_item(shipping_status='해외배송중(통관)'), _screen())[0] == 'shipped'
    # 공백뿐인 송장·발송 아닌 배송상태는 그대로 화면 판정으로 간다
    assert decide(_item(tracking_number='  '), _screen())[0] == 'failed'
    assert decide(_item(shipping_status='배송준비중'), _screen())[0] == 'failed'
    # 묶음이 발송보다 먼저다
    assert decide(_item(bundle_count=2, tracking_number='1234567890'), None)[0] == 'bundle'


def test_decide_화면없음_로그인실패_못찾음은_failed다():
    assert decide(_item(), None)[0] == 'failed'
    assert decide(_item(), _screen(login=False))[0] == 'failed'
    assert decide(_item(), _screen(found=False))[0] == 'failed'
    # 사유는 비어 있지 않다(메모에 실린다)
    assert decide(_item(), None)[1]


def test_decide_상품행_2개는_bundle이다():
    assert decide(_item(), _screen(items=2)) == ('bundle', '화면 상품행 2개')


def test_decide_발송_기취소_접수상태를_그대로_옮긴다():
    assert decide(_item(), _screen(state='shipped'))[0] == 'shipped'
    assert decide(_item(), _screen(state='already_cancelled'))[0] == 'already_cancelled'
    assert decide(_item(), _screen(state='cancel_pending'))[0] == 'accepted'


def test_decide_check모드에서_취소가능이면_누르지_않고_failed다():
    # 통제자 판정: check 화면은 절대 클릭으로 이어지지 않는다 — 삼바가 cancel 로 다시 내주거나 사람에게
    assert decide(_item(mode='check'), _screen()) == (
        'failed',
        '재확인 중 다시 취소 가능 상태 — 사람 확인',
    )


def test_decide_cancel모드_클릭후_확인으로만_성공을_친다():
    assert decide(_item(), _screen(clicked=True, after_state='already_cancelled'))[0] == 'cancelled'
    assert decide(_item(), _screen(clicked=True, after_state='cancel_pending'))[0] == 'accepted'
    assert decide(_item(), _screen(clicked=True, after_state='cancellable')) == (
        'failed',
        '클릭 후 확인 안 됨',
    )
    assert decide(_item(), _screen(clicked=True, after_state='')) == (
        'failed',
        '클릭 후 확인 안 됨',
    )


def test_decide_unknown이거나_버튼이_1개가_아니면_failed다():
    assert decide(_item(), _screen(state='unknown'))[0] == 'failed'
    assert decide(_item(), _screen(buttons=0))[0] == 'failed'
    assert decide(_item(), _screen(buttons=2))[0] == 'failed'
    assert decide(_item(mode='check'), _screen(state='unknown'))[0] == 'failed'


# ---- 주문번호 토큰 일치 ----


def test_order_no_token_match():
    text = '주문번호 2026102812345'
    assert order_no_token_match(text, '02810') is False
    assert order_no_token_match(text, '2026102812345') is True
    assert order_no_token_match('M20261028777 결제완료', 'M20261028777') is True
    assert order_no_token_match('', '1') is False


# ---- 구매 계정 결정 ----


def test_resolve_profile():
    one = Source(id='MUSINSA', key='musinsa', label='무신사', buy_accounts=['buy-1'])
    many = Source(id='GrandStage', key='abc', label='그랜드', buy_accounts=['b1', 'b2'])
    none = Source(id='TheHyundai', key='thehyundai', label='더현대닷컴')
    # a) 장부에 적힌 발주 계정(키마스터 라벨)이 먼저다
    assert resolve_profile(many, 'b2', ['b1', 'b2'], ledger_account='b1') == 'b1'
    assert resolve_profile(none, None, [], ledger_account='hy-1') == 'hy-1'
    assert resolve_profile(none, None, [], ledger_account='  ') is None
    # b) 아이디가 라벨과 정확히 같으면 그 라벨
    assert resolve_profile(many, 'b2', ['b1', 'b2']) == 'b2'
    # c) 아니면 buy_accounts 가 1개일 때 그 계정
    assert resolve_profile(one, 'someone', ['x']) == 'buy-1'
    assert resolve_profile(one, None, []) == 'buy-1'
    # 셋 다 아니면 None
    assert resolve_profile(many, 'nobody', ['b1', 'b2']) is None
    assert resolve_profile(many, None, []) is None
    assert resolve_profile(none, 'someone', []) is None


# ---- 실행기 ----


class _Wave:
    def __init__(self, items: list[RobotCancelItem], states: dict[str, str] | None = None) -> None:
        self.items = items
        self.states = states or {}
        self.listed: list[set[str] | None] = []
        self.results: list[tuple[str, str, str]] = []
        self.fail_post = False

    def robot_cancels(self, limit: int = 20, sites: set[str] | None = None):
        self.listed.append(sites)
        out, self.items = self.items, []
        return out

    def post_robot_cancel_result(self, cancel_id: str, outcome: str, reason: str = '') -> str:
        if self.fail_post:
            raise WaveError(FailReason.UNKNOWN, '삼바 응답 500', 500)
        self.results.append((cancel_id, outcome, reason))
        return self.states.get(cancel_id, 'done')


class _Notify:
    def __init__(self, ok: bool = True) -> None:
        self.ok = ok
        self.cards: list[tuple[str, str, str, str]] = []

    def card(self, level: str, title: str, conclusion: str, todo: str) -> bool:
        self.cards.append((level, title, conclusion, todo))
        return self.ok


class _Script:
    """run_script 가짜 — mode 별로 돌려줄 화면을 정한다. 호출 args 를 전부 남긴다."""

    def __init__(self, by_mode: dict[str, dict[str, object] | None]) -> None:
        self.by_mode = by_mode
        self.calls: list[tuple[str, dict[str, object]]] = []

    def __call__(self, name: str, args: dict[str, object]) -> dict[str, object] | None:
        self.calls.append((name, dict(args)))
        return self.by_mode.get(str(args['mode']))


def _runner(
    wave: _Wave,
    script: _Script,
    notify: _Notify | None = None,
    *,
    enabled=lambda site: True,
    idle=lambda: True,
    profiles=lambda site: ['buy-1'],
    ledger_account=lambda source_order_no: None,
    sites: set[str] | None = None,
) -> tuple[SourceCanceller, _Notify]:
    notify = notify or _Notify()
    runner = SourceCanceller(
        wave,  # type: ignore[arg-type]
        script,
        notify,  # type: ignore[arg-type]
        enabled=enabled,
        idle=idle,
        profiles=profiles,
        ledger_account=ledger_account,
        sites=sites,
        sources=_sources(),
    )
    return runner, notify


def test_reclaimed_row_checks_first():
    # 재선점(claimed 방치) 행은 mode=check 로 온다 — 상태만 읽고 절대 누르지 않는다(cancel 호출 0회).
    # 다시 취소 가능이면 failed 로 회신 → 삼바가 retry(30분 뒤 cancel 모드)로 내주거나 사람에게 넘긴다
    wave = _Wave([_item(mode='check')], states={'rc_1': 'retry'})
    script = _Script(
        {
            'check': _screen(),
            'cancel': _screen(clicked=True, after_state='already_cancelled'),
        }
    )
    runner, notify = _runner(wave, script)
    assert runner.run_once() == ['failed']
    assert [a['mode'] for _, a in script.calls] == ['check']
    name, args = script.calls[0]
    assert name == 'musinsa_order_cancel'
    assert args == {
        'source_order_no': 'M20261028777',
        'profile': 'buy-1',
        'mode': 'check',
        'reason_text': '단순 변심',
    }
    assert wave.results == [('rc_1', 'failed', '재확인 중 다시 취소 가능 상태 — 사람 확인')]
    assert notify.cards == []


def test_cancel모드는_스크립트_1회로_누르고_되읽는다():
    wave = _Wave([_item()])
    script = _Script({'cancel': _screen(clicked=True, after_state='already_cancelled')})
    runner, notify = _runner(wave, script)
    assert runner.run_once() == ['cancelled']
    assert [a['mode'] for _, a in script.calls] == ['cancel']
    assert wave.results == [('rc_1', 'cancelled', '')]
    assert notify.cards == [
        ('ok', '20261028001 · 무신사', '소싱처 취소 완료', '마켓 취소승인 눌러주세요')
    ]


def test_장부_계정이_있으면_그_라벨로_스크립트를_부른다():
    wave = _Wave([_item(source_site='LOTTEON', account_username='nobody')])
    script = _Script({'cancel': _screen(clicked=True, after_state='already_cancelled')})
    runner, _ = _runner(
        wave,
        script,
        profiles=lambda site: ['b1', 'b2'],
        ledger_account=lambda no: 'b2' if no == 'M20261028777' else None,
    )
    assert runner.run_once() == ['cancelled']
    assert script.calls[0][0] == 'lotteon_order_cancel'
    assert script.calls[0][1]['profile'] == 'b2'


def test_check모드에서_이미_발송이면_cancel을_부르지_않는다():
    wave = _Wave([_item(mode='check')])
    script = _Script({'check': _screen(state='shipped'), 'cancel': _screen()})
    runner, notify = _runner(wave, script)
    assert runner.run_once() == ['shipped']
    assert [a['mode'] for _, a in script.calls] == ['check']
    assert notify.cards[0][0] == 'warn'


def test_disabled_site_not_reported():
    wave = _Wave([_item(source_site='THEHYUNDAI'), _item(id='rc_2')])
    script = _Script({'cancel': _screen(clicked=True, after_state='already_cancelled')})
    runner, notify = _runner(
        wave, script, enabled=lambda site: site.lower() == 'musinsa', sites={'MUSINSA'}
    )
    assert runner.run_once() == ['cancelled']
    # 목록 호출에 켜진 사이트를 넘긴다
    assert wave.listed == [{'MUSINSA'}]
    # 꺼진 사이트는 회신도 스크립트 호출도 없다 — 15분 뒤 삼바가 다시 내준다
    assert wave.results == [('rc_2', 'cancelled', '')]
    assert len(script.calls) == 1
    assert len(notify.cards) == 1


def test_idle_false_stops_loop():
    # 통제자 판정(최종 리뷰): 목록 호출이 곧 선점이라 idle 이 아니면 목록도 부르지 않는다
    wave = _Wave([_item(id='rc_1'), _item(id='rc_2')])
    script = _Script({'cancel': _screen(clicked=True, after_state='already_cancelled')})
    runner, _ = _runner(wave, script, idle=lambda: False)
    assert runner.run_once() == []
    assert wave.listed == []
    assert script.calls == []
    assert wave.results == []
    # 목록 뒤 건 사이에 바빠지면 남은 건은 손대지 않는다(건마다 idle 재확인)
    wave = _Wave([_item(id='rc_1'), _item(id='rc_2')])
    script = _Script({'cancel': _screen(clicked=True, after_state='already_cancelled')})
    flags = iter([True, True, False])
    runner, _ = _runner(wave, script, idle=lambda: next(flags))
    assert runner.run_once() == ['cancelled']
    assert wave.listed == [None]
    assert [c for c, _, _ in wave.results] == ['rc_1']


def test_telegram_failure_does_not_block_result():
    wave = _Wave([_item()])
    script = _Script({'cancel': _screen(clicked=True, after_state='already_cancelled')})
    runner, notify = _runner(wave, script, _Notify(ok=False))
    assert runner.run_once() == ['cancelled']
    assert wave.results == [('rc_1', 'cancelled', '')]
    assert len(notify.cards) == 1
    # 다음 사이클 — 삼바가 더 내주지 않으면(done) 같은 건을 다시 보내지 않는다
    assert runner.run_once() == []
    assert len(notify.cards) == 1


def test_retry_state_no_telegram():
    wave = _Wave([_item()], states={'rc_1': 'retry'})
    script = _Script({'cancel': None})
    runner, notify = _runner(wave, script)
    assert runner.run_once() == ['failed']
    assert wave.results[0][1] == 'failed'
    assert notify.cards == []


def test_accepted_recheck_no_telegram():
    # 처음(cancel) 접수는 1통, 재확인(check)에서 다시 접수면 0통
    first = _Wave([_item()], states={'rc_1': 'wait_confirm'})
    runner, notify = _runner(
        first, _Script({'cancel': _screen(clicked=True, after_state='cancel_pending')})
    )
    assert runner.run_once() == ['accepted']
    assert len(notify.cards) == 1 and notify.cards[0][0] == 'warn'

    again = _Wave([_item(mode='check')], states={'rc_1': 'wait_confirm'})
    runner, notify = _runner(again, _Script({'check': _screen(state='cancel_pending')}))
    assert runner.run_once() == ['accepted']
    assert again.results == [('rc_1', 'accepted', '')]
    assert notify.cards == []


def test_접수가_done으로_닫히면_72시간_만료_실패_카드다():
    # check 재확인에서 접수인데 삼바가 done 을 돌려줌 = 72시간 만료 → 실패 카드 정확히 1통
    recheck = _Wave([_item(mode='check')], states={'rc_1': 'done'})
    runner, notify = _runner(recheck, _Script({'check': _screen(state='cancel_pending')}))
    assert runner.run_once() == ['accepted']
    assert recheck.results == [('rc_1', 'accepted', '')]
    assert notify.cards == [
        (
            'bad',
            '20261028001 · 무신사',
            '자동취소 실패: 취소 접수 후 72시간 확정 안 됨',
            '직접 취소',
        )
    ]
    # cancel 모드에서 접수했는데 done 이어도 접수 카드가 아니라 실패 카드다
    first = _Wave([_item()], states={'rc_1': 'done'})
    runner, notify = _runner(
        first, _Script({'cancel': _screen(clicked=True, after_state='cancel_pending')})
    )
    assert runner.run_once() == ['accepted']
    assert len(notify.cards) == 1
    assert notify.cards[0][0] == 'bad'
    assert '72시간' in notify.cards[0][2]


def test_반영_안_된_회신은_텔레그램을_보내지_않는다():
    wave = _Wave([_item()], states={'rc_1': 'skipped'})
    script = _Script({'cancel': _screen(clicked=True, after_state='already_cancelled')})
    runner, notify = _runner(wave, script)
    assert runner.run_once() == ['cancelled']
    assert notify.cards == []


def test_소싱처_설정이_없으면_failed로_회신한다():
    wave = _Wave([_item(source_site='NOWHERE')])
    script = _Script({'cancel': _screen()})
    runner, notify = _runner(wave, script)
    assert runner.run_once() == ['failed']
    assert wave.results == [('rc_1', 'failed', '소싱처 설정 없음')]
    assert script.calls == []
    assert notify.cards[0][0] == 'bad'
    assert notify.cards[0][1] == '20261028001 · NOWHERE'


def test_소싱처_id는_대소문자를_가리지_않는다():
    wave = _Wave([_item(source_site='musinsa')])
    script = _Script({'cancel': _screen(clicked=True, after_state='already_cancelled')})
    runner, _ = _runner(wave, script)
    assert runner.run_once() == ['cancelled']
    assert script.calls[0][0] == 'musinsa_order_cancel'


def test_실제_sources_yaml_더현대는_thehyundai_키이고_미검증이라_스크립트_없이_실패한다():
    # 회귀: 가짜 표가 THEHYUNDAI→hmall 로 돼 있던 실수. 실제 표를 읽어 고정한다
    real = default_sources()
    src = real.by_id('THEHYUNDAI')
    assert src is not None and src.key == 'thehyundai' and src.id == 'TheHyundai'
    assert src.buy_accounts == []
    # 장부도 buy_accounts 도 없으면 추측하지 않고 실패한다
    assert resolve_profile(src, 'someone', list(src.buy_accounts)) is None
    # 미검증 사이트(SITE_VERIFIED False)는 계정 판단보다 먼저 사람에게 넘긴다 — 스크립트 호출 0회
    wave = _Wave([_item(source_site='THEHYUNDAI', account_username='someone')])
    script = _Script({'cancel': _screen()})
    runner = SourceCanceller(
        wave,  # type: ignore[arg-type]
        script,
        _Notify(),  # type: ignore[arg-type]
        enabled=lambda site: True,
        idle=lambda: True,
        profiles=lambda site: list(real.by_id(site).buy_accounts),  # type: ignore[union-attr]
        sources=real,
    )
    assert runner.run_once() == ['failed']
    assert wave.results == [('rc_1', 'failed', '미검증 사이트 — 직접 취소')]
    assert script.calls == []
    # 장부 계정이 있어도 미검증이면 실제 표로도 thehyundai_order_cancel 을 부르지 않는다
    wave2 = _Wave([_item(source_site='THEHYUNDAI')])
    script2 = _Script({'cancel': _screen(clicked=True, after_state='already_cancelled')})
    runner2 = SourceCanceller(
        wave2,  # type: ignore[arg-type]
        script2,
        _Notify(),  # type: ignore[arg-type]
        enabled=lambda site: True,
        idle=lambda: True,
        profiles=lambda site: [],
        ledger_account=lambda no: 'hy-1',
        sources=real,
    )
    assert runner2.run_once() == ['failed']
    assert wave2.results == [('rc_1', 'failed', '미검증 사이트 — 직접 취소')]
    assert script2.calls == []


def test_구매_계정을_못_정하면_failed다():
    wave = _Wave([_item(source_site='LOTTEON', account_username='nobody')])
    script = _Script({'cancel': _screen()})
    runner, _ = _runner(wave, script, profiles=lambda site: ['b1', 'b2'])
    assert runner.run_once() == ['failed']
    assert wave.results == [('rc_1', 'failed', '구매 계정을 정하지 못함')]
    assert script.calls == []


def test_묶음은_스크립트를_부르지_않는다():
    wave = _Wave([_item(bundle_count=2)])
    script = _Script({'cancel': _screen()})
    runner, notify = _runner(wave, script)
    assert runner.run_once() == ['bundle']
    assert script.calls == []
    assert notify.cards[0][2] == '묶음 주문이라 손대지 않음'


def test_삼바_발송_사전판정은_계정_결정과_스크립트_없이_shipped로_회신한다():
    # 계정을 못 정하는 소싱처라도 삼바 송장/배송상태가 발송이면 스크립트·계정 판단 전에 shipped
    wave = _Wave(
        [
            _item(
                id='rc_1', source_site='LOTTEON', account_username='nobody', tracking_number='T1'
            ),
            _item(id='rc_2', shipping_status='배송완료'),
        ]
    )
    script = _Script({'cancel': _screen(clicked=True, after_state='already_cancelled')})
    runner, notify = _runner(wave, script, profiles=lambda site: ['b1', 'b2'])
    assert runner.run_once() == ['shipped', 'shipped']
    assert script.calls == []
    assert wave.results == [
        ('rc_1', 'shipped', '삼바 송장/배송상태로 발송 확인'),
        ('rc_2', 'shipped', '삼바 송장/배송상태로 발송 확인'),
    ]
    assert [c[2] for c in notify.cards] == ['이미 발송돼 취소 못 함'] * 2
    # 묶음이면 발송보다 묶음이 먼저다
    wave = _Wave([_item(bundle_count=2, tracking_number='T1')])
    script = _Script({'cancel': _screen()})
    runner, _ = _runner(wave, script)
    assert runner.run_once() == ['bundle']
    assert script.calls == []


@pytest.mark.parametrize('site', ['FashionPlus', 'GrandStage', 'GSShop', 'THEHYUNDAI'])
def test_미검증_사이트는_스크립트_없이_즉시_실패로_회신한다(site: str):
    # 통제자 판정(최종 리뷰): SITE_VERIFIED 가 False·없음이면 조용히 기다리지 않고 바로 사람에게 넘긴다.
    # 첫 실패는 삼바가 retry 로 돌려줘 카드 없음, 두 번째(done)에 실패 카드 1통
    wave = _Wave([_item(source_site=site)], states={'rc_1': 'retry'})
    script = _Script({'cancel': _screen(clicked=True, after_state='already_cancelled')})
    runner, notify = _runner(wave, script, ledger_account=lambda no: 'any-1')
    assert runner.run_once() == ['failed']
    assert wave.results == [('rc_1', 'failed', '미검증 사이트 — 직접 취소')]
    assert script.calls == []
    assert notify.cards == []

    wave = _Wave([_item(source_site=site, attempts=1)], states={'rc_1': 'done'})
    runner, notify = _runner(wave, script, ledger_account=lambda no: 'any-1')
    assert runner.run_once() == ['failed']
    assert script.calls == []
    assert len(notify.cards) == 1
    assert notify.cards[0][0] == 'bad'
    assert notify.cards[0][2] == '자동취소 실패: 미검증 사이트 — 직접 취소'


def test_회신_실패는_다음_건으로_넘어가고_텔레그램은_없다():
    wave = _Wave([_item(id='rc_1'), _item(id='rc_2')])
    wave.fail_post = True
    script = _Script({'cancel': _screen(clicked=True, after_state='already_cancelled')})
    runner, notify = _runner(wave, script)
    assert runner.run_once() == []
    assert len(script.calls) == 2
    assert notify.cards == []


@pytest.mark.parametrize(
    ('outcome', 'level', 'conclusion', 'todo'),
    [
        ('cancelled', 'ok', '소싱처 취소 완료', '마켓 취소승인 눌러주세요'),
        ('already_cancelled', 'ok', '소싱처 취소 완료', '마켓 취소승인 눌러주세요'),
        ('accepted', 'warn', '소싱처 취소 접수(판매자 확인 대기)', '확정되면 다시 알림'),
        ('shipped', 'warn', '이미 발송돼 취소 못 함', '반품 처리 필요'),
        ('bundle', 'warn', '묶음 주문이라 손대지 않음', '직접 확인'),
        ('failed', 'bad', '자동취소 실패: 로그인 안 됨', '직접 취소'),
    ],
)
def test_텔레그램_문구표(outcome: str, level: str, conclusion: str, todo: str):
    from samba_agent.ops.source_cancel import card_for

    assert card_for(outcome, '로그인 안 됨') == (level, conclusion, todo)
