"""삼바 주문화면 승인카드 연동 — 승인요청 등록 + 결정 폴링 재개 + 단계 이벤트 적재(사용자 2026-10-09).

백엔드는 로봇을 부르지 못한다(로봇 API 는 127.0.0.1 전용). 그래서 로봇이
① 결제 직전 멈출 때 `POST /orders/{key}/approval` 로 요약을 올리고
② `GET /orders/{key}/approval` 을 주기적으로 봐서 approved/rejected/expired 면 `worker.resume` 으로 그래프를 깨운다.
③ 에이전트 결과·보고 한 줄을 `POST /orders/{key}/events` 로 남긴다(사장님 요구: 모든 단계 수집).

어느 호출이 실패해도(백엔드 잠시 죽음) 스레드·작업을 죽이지 않는다 — 다음 주기에 다시 본다.
개인정보는 보내기 전에 mask_text 로 가린다.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable

from samba_agent.ops.masking import mask_text
from samba_agent.queue.db import Job, JobQueue
from samba_agent.wave.client import WaveClient, WaveError

_log = logging.getLogger(__name__)

WAITING_PREFIX = '승인 대기: '
# 삼바가 돌려주는 상태 가운데 '사람이 결정했다/대기가 끝났다' 로 볼 것
_DECIDED = {'approved', 'rejected', 'expired', 'replaced'}
# 요약 문장에서 구조화 값으로 뽑는 줄 — approval.approval_request 가 만든 형식
_ACCOUNT_CARD = re.compile(r'계정:\s*(?P<account>[^·]+?)\s*·\s*카드:\s*(?P<card>.+)$')
_COST_MARGIN = re.compile(r'원가:\s*(?P<cost>[\d,]+)원\s*·\s*마진:\s*(?P<margin>[-\d.]+)%')
_MAX_EVIDENCE = 20

ResumeFn = Callable[[str, bool, str, str | None], Job | None]


def waiting_stage(job: Job) -> str | None:
    """승인 대기 중인 작업이면 그 단계 이름(pay/record), 아니면 None."""
    step = job.step or ''
    if job.state != 'needs_human' or not step.startswith(WAITING_PREFIX):
        return None
    return step[len(WAITING_PREFIX) :].strip() or None


def payload_from_request(req: dict[str, object]) -> dict[str, object]:
    """승인 요청 원본(summary·evidence) → 카드가 쓸 구조화 값. 번호·주소는 이미 가려져 있다."""
    out: dict[str, object] = {}
    summary = str(req.get('summary') or '')
    for line in summary.splitlines():
        m = _ACCOUNT_CARD.search(line)
        if m:
            out['account'] = m.group('account').strip()
            out['card'] = m.group('card').strip()
        m = _COST_MARGIN.search(line)
        if m:
            try:
                out['cost'] = int(m.group('cost').replace(',', ''))
                out['margin_pct'] = float(m.group('margin'))
            except ValueError:
                pass
    evidence = req.get('evidence')
    if isinstance(evidence, list):
        out['evidence'] = [
            {
                'label': str(e.get('label', ''))[:40],
                'detail': mask_text(str(e.get('detail', '')))[:200],
            }
            for e in evidence[:_MAX_EVIDENCE]
            if isinstance(e, dict)
        ]
    return out


class WaveApprovalRelay:
    """승인요청 등록 + 결정 폴링. 워커 스레드와 별도 스레드에서 돈다."""

    def __init__(
        self, wave: WaveClient, queue: JobQueue, resume: ResumeFn, poll_s: float = 2.0
    ) -> None:
        self._wave = wave
        self._queue = queue
        self._resume = resume
        self._poll_s = poll_s
        # 이번 기동에서 승인요청을 올린 작업 키 — 삼바에 요청이 없으면(재기동·등록 실패) 다시 올린다
        self._requested: set[str] = set()

    def request(self, job: Job, req: dict[str, object]) -> None:
        """결제 직전 멈춘 작업의 요약을 삼바에 올린다. 실패는 로그만(폴러가 다시 올린다)."""
        stage = str(req.get('stage') or 'pay')
        summary = mask_text(str(req.get('summary') or ''))
        try:
            self._wave.post_approval(
                job.key, stage=stage, summary=summary, payload=payload_from_request(req)
            )
        except (WaveError, Exception) as e:  # noqa: BLE001 — 등록 실패가 작업을 막으면 안 된다
            _log.warning('승인요청 등록 실패 %s(%s)', job.order_no, type(e).__name__)
            return
        self._requested.add(job.key)
        _log.info('승인요청 등록 %s %s', job.order_no, stage)

    def poll_once(self) -> int:
        """승인 대기 작업마다 삼바 상태를 본다. 결정이 있으면 재개. 재개한 건수."""
        resumed = 0
        try:
            jobs = self._queue.live()
        except Exception:  # noqa: BLE001 — 큐 조회 실패도 스레드를 죽이면 안 된다
            _log.exception('승인 폴링: 큐 조회 실패')
            return 0
        for job in jobs:
            stage = waiting_stage(job)
            if stage is None:
                continue
            try:
                status = self._wave.get_approval(job.key, stage=stage)
            except (WaveError, Exception) as e:  # noqa: BLE001
                _log.warning('승인 폴링 실패 %s(%s) — 다음 주기에 다시 본다', job.order_no, type(e).__name__)
                continue
            state = str(status.get('state') or 'none')
            if state == 'none':
                if job.key not in self._requested:
                    # 재기동·등록 실패로 삼바에 요청이 없다 — 요약 없이라도 카드를 띄운다
                    self.request(
                        job,
                        {
                            'stage': stage,
                            'summary': f'*{stage} 승인 요청* — 주문 {job.order_no}\n(로봇 재기동 — 근거는 로봇 로그 참고)',
                        },
                    )
                continue
            if state not in _DECIDED:
                continue  # pending — 계속 기다린다
            approved = state == 'approved'
            by = str(status.get('by') or ('samba-ui' if approved else state))
            if state == 'replaced':
                # 새 요청으로 교체됐다(우리가 다시 올린 것) — 대기 계속
                continue
            try:
                out = self._resume(job.key, approved, by, stage)
            except Exception:  # noqa: BLE001 — 재개 중 예외는 워커가 needs_human 으로 마감한다
                _log.exception('승인 재개 중 오류 %s', job.order_no)
                self._requested.discard(job.key)
                continue
            self._requested.discard(job.key)
            if out is None:
                _log.info('승인 %s 받았으나 대기 상태가 아니다 — 재개하지 않는다(%s)', state, job.order_no)
                continue
            resumed += 1
            _log.info('승인 %s(%s) → 재개 %s', state, by, job.order_no)
        return resumed

    def run_forever(self, stop: Callable[[], bool]) -> None:
        while not stop():
            try:
                self.poll_once()
            except Exception:  # noqa: BLE001 — 어떤 예외도 스레드를 죽이면 안 된다
                _log.exception('승인 폴링 고리 오류 — 계속한다')
            time.sleep(self._poll_s)


_SEVERITY = {'ok': 'info', 'needs_human': 'warn', 'fail': 'error'}


class WaveEventSink:
    """로봇 단계 이벤트를 삼바 samba_purchase_event 에 적재한다. 실패는 로그만."""

    def __init__(self, wave: WaveClient) -> None:
        self._wave = wave

    def _send(self, key: str | None, item: dict[str, object]) -> None:
        try:
            self._wave.post_events(key, [item])
        except (WaveError, Exception) as e:  # noqa: BLE001 — 이벤트 적재 실패가 작업을 막으면 안 된다
            _log.warning('이벤트 적재 실패 %s(%s)', item.get('code'), type(e).__name__)

    def agent_result(
        self, state: dict, stage: str, agent: str, result: object, duration_ms: int, attempt: int
    ) -> None:
        """에이전트 1회 실행 결과 → 이벤트 1건. code = stage.status 또는 stage.fail_reason."""
        status = str(getattr(result, 'status', '') or 'unknown')
        fail_reason = getattr(result, 'fail_reason', None)
        code = f'{stage}.{status}' if status == 'ok' else f'{stage}.{fail_reason or status}'
        payload = getattr(result, 'payload', None) or {}
        order = state.get('order')
        key = str(getattr(order, 'wave_key', '') or getattr(order, 'order_no', '') or '') or None
        item: dict[str, object] = {
            'stage': stage,
            'code': code[:80],
            'severity': _SEVERITY.get(status, 'warn'),
            'message': mask_text(str(getattr(result, 'reason', '') or ''))[:300],
            'detail': {
                'agent': agent,
                'status': status,
                'fail_reason': str(fail_reason) if fail_reason else None,
                'duration_ms': duration_ms,
                'attempt': attempt,
                'dry_run': bool(state.get('dry_run', True)),
            },
            'job_key': key,
        }
        if isinstance(payload, dict):
            if payload.get('account'):
                item['account_label'] = mask_text(str(payload['account']))[:60]
            if payload.get('card'):
                item['pay_method'] = str(payload['card'])[:60]
            for k in ('cost', 'margin_pct', 'option', 'order_type'):
                if k in payload:
                    item['detail'][k] = payload[k]  # type: ignore[index]
        self._send(key, item)

    def line(self, job: Job, text: str) -> None:
        """보고 한 줄(접수·건너뜀·완료·오류) → system.report 이벤트."""
        self._send(
            job.key,
            {
                'stage': 'system',
                'code': 'system.report',
                'severity': 'info',
                'message': mask_text(text)[:300],
                'detail': {'state': job.state, 'step': job.step},
                'job_key': job.key,
            },
        )
