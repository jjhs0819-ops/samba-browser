// 무신사 주문취소(2026-10-28 실측: 결제 완료 화면의 버튼 "주문 취소" · 배송중 · 배송 완료(3상품) · 취소 완료).
// 확인창·사유 화면 문구 미확인 — 누른 뒤 화면을 다시 읽어 after_state 로만 성공을 판정한다.
// 인자 {source_order_no, profile, mode:'check'|'cancel', reason_text} · 반환 {source_order_no, login, found, items, state, buttons, clicked, after_state, note}
// mode=check 는 절대 누르지 않는다. mode=cancel 은 VERIFIED·login·found·items==1·state==cancellable·buttons==1 일 때만 1번 누른다.
// 판정 규칙(RULES·CONFIRM·VERIFIED)은 samba_agent/ops/cancel_screen.py 의 SITE_RULES·SITE_CONFIRM·SITE_VERIFIED 와 같은 값 — 드리프트 테스트가 비교한다.
// 앱은 자동화(full) 모드에서 페이지의 confirm() 을 자동 '예' 한다(src/main/browser/dialogs.ts) — 첫 클릭이 전체 가드 뒤라 사이트 확인창과 같은 뜻으로 본다(리뷰 1차 판정).
const RULES = {"segment": ["주문 상품 \\d+개", "결제 정보"], "items": "주문 상품 (\\d+)개", "buttons": ["주문 취소"], "shipped": ["배송 완료", "배송중", "배송 중", "배송 준비 중", "상품 준비 중", "구매 확정", "반품", "교환", "환불 완료"], "already_cancelled": ["취소 완료"], "cancel_pending": ["취소 요청", "취소 접수"], "cancellable": ["결제 완료"]}
const CONFIRM = ["취소 신청", "신청하기", "취소 요청"]
const VERIFIED = true
const nz = s => String(s || '').replace(/\s+/g, ' ').trim()
const no = nz(args.source_order_no || args.orderNo).replace(/[^0-9A-Za-z]/g, '')
const mode = args.mode === 'cancel' ? 'cancel' : 'check'
const reason = nz(args.reason_text || '단순 변심')
const R = { source_order_no: no || null, login: true, found: false, items: 0, state: 'unknown', buttons: 0, clicked: false, after_state: '', note: null }
if (!no) return { ...R, note: 'no order number' }
const pf = args.profile ? { profile: args.profile } : {}
const opened = []
const open = async url => { const id = (String(await tabs.open({ ...pf, url })).match(/tab (\S+)/) || [])[1]; if (id) { opened.push(id); await tabs.switch(id) } }
const done = async r => { for (const id of opened) { try { await tabs.close(id) } catch (e) {} } return r }
const esc = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
const mask = s => s.replace(/01\d[-.\s]?\d{3,4}[-.\s]?\d{4}|\d{2,4}-\d{3,4}-\d{4}/g, '[가림]').slice(0, 300)
const tree = async () => String((await page.get({})).tree || '')
const elems = t => t.split('PAGE TEXT')[0].split('\n').map(l => l.match(/^\[(\d+)\] (\S+)(?: "([^"]*)")?/)).filter(Boolean).map(m => ({ id: +m[1], role: m[2], t: (m[3] || '').trim(), key: m[0] }))
const body = t => nz((t.split('PAGE TEXT')[1] || '').replace(/^:/, ''))
// 정확한 글자의 button·link, 그게 없을 때만 clickable(앱이 한 버튼을 button+clickable 로 두 번 보여 준다) — cancel_screen.count_buttons 와 같다
const exact = (es, labels) => { const c = es.filter(e => labels.includes(e.t)); const s = c.filter(e => /^(button|link)$/.test(e.role)); return s.length ? s : c.filter(e => e.role === 'clickable') }
const classify = (t, url) => {
  const b = body(t)
  const out = { login: !(/\/login/i.test(url) || /아이디 저장|로그인하시면/.test(b)), found: new RegExp('(?<![0-9A-Za-z])' + esc(no) + '(?![0-9A-Za-z])').test(b), items: 0, state: 'unknown', buttons: 0, seg: '', segOk: false }
  if (!b) return out
  let seg = b
  if (RULES.segment[0]) { const m = seg.match(new RegExp(RULES.segment[0])); if (m) { seg = seg.slice(m.index); out.segOk = true } }
  if (RULES.segment[1]) { const m = seg.match(new RegExp(RULES.segment[1])); if (m) seg = seg.slice(0, m.index) }
  const im = [...seg.matchAll(new RegExp(RULES.items, 'g'))]
  out.items = /\((?!\?)/.test(RULES.items) ? (im[0] ? parseInt(im[0][1], 10) || 0 : 0) : im.length
  for (const st of ['shipped', 'already_cancelled', 'cancel_pending', 'cancellable']) if (RULES[st].some(w => seg.includes(w))) { out.state = st; break }
  out.buttons = exact(elems(t), RULES.buttons).length
  out.seg = seg
  return out
}
// 로그 증거: 상품 구간 시작 글자를 못 찾으면 본문 대신 요약만(고객 이름이 로그에 안 가게)
const summary = c => '상태 ' + c.state + ' · 상품행 ' + c.items + ' · 버튼 ' + c.buttons
const noteOf = c => c.segOk ? mask(c.seg) : summary(c)
// page.get({}) 는 보이는 것부터 150개만 나열한다(src/shared/snapshot.ts) — 버튼 수·확인 버튼은 글자 검색(page.get({query}), 문서 전체·원래 id)으로 센다
const labeled = async labels => { const seen = new Map(); for (const q of new Set(labels)) for (const e of elems(String((await page.get({ query: q })).tree || ''))) seen.set(e.id, e); return [...seen.values()] }
// 공제·수수료 글자가 클릭 전보다 늘었는가(전체 본문 기준) — cancel_screen.deduction_increased 와 같다
const DED = ["공제", "취소 수수료", "위약금", "차감"]
const dedCounts = s => DED.map(p => (s.match(new RegExp(p, 'g')) || []).length)
const dedUp = (b0, b1) => { const a = dedCounts(b0), z = dedCounts(b1); return z.some((n, i) => n > a[i]) }
await open('https://www.musinsa.com/order/order-detail/' + no)
try { await page.waitFor(/결제 정보|주문 상품|로그인/, 10000) } catch (e) {}
await sleep(800)
let t = await tree()
const c = classify(t, await page.url())
// 취소 버튼 수는 문서 전체 글자 검색으로(150개 밖의 같은 버튼도 센다)
const firstBtns = exact(await labeled(RULES.buttons), RULES.buttons)
c.buttons = firstBtns.length
Object.assign(R, { login: c.login, found: c.found, items: c.items, state: c.state, buttons: c.buttons, note: noteOf(c) })
if (mode !== 'cancel') return done(R)
if (!VERIFIED) return done({ ...R, note: '조건 미충족 — 미검증 사이트: ' + summary(c) })
if (!(c.login && c.found && c.items === 1 && c.state === 'cancellable' && c.buttons === 1)) return done({ ...R, note: '조건 미충족 — 누르지 않음: ' + noteOf(c) })
// 클릭 전: 확인 후보 글자를 가진 요소의 id(원래 id, 같은 문서 안에서 안정)와 본문을 기억한다 — 그 뒤 새 id 만 확인 버튼으로 본다
const url0 = await page.url()
const pre = new Set((await labeled([...CONFIRM, ...RULES.buttons, '확인'])).map(e => e.id))
const body0 = body(t)
// 1) 취소 버튼 1개 클릭(여기까지가 전체 가드)
await page.click(firstBtns[0].id)
R.clicked = true
try { await page.waitFor(/취소|사유/, 8000) } catch (e) {}
await sleep(1200)
t = await tree()
// 주소가 바뀌었으면 새 문서라 id 가 처음부터 다시 매겨진다 — 그때는 클릭 전 id 집합을 쓰지 않는다
const isNew = async e => (await page.url()) !== url0 || !pre.has(e.id)
const newExact = async labels => { const out = []; for (const e of exact(await labeled(labels), labels)) if (await isNew(e)) out.push(e); return out }
const steps = ['클릭']
if (dedUp(body0, body(t))) steps.push('공제 금액 표시 — 사람 확인')
else {
  // 2) 사유: '단순 변심' 계열 — select 는 글자로, 새 라디오/버튼이면 1클릭
  const variants = [reason, reason.replace(/\s/g, ''), '단순변심', '단순 변심', '구매 의사 취소', '고객 변심']
  const found = await labeled(variants)
  const sel = found.find(e => e.role === 'select')
  if (sel) { for (const v of variants) { try { await page.select(sel.id, v); steps.push('사유 ' + v); break } catch (e) {} } }
  else { for (const opt of found) if (/^(radio|option|clickable|button|label)$/.test(opt.role) && variants.includes(opt.t) && (await isNew(opt))) { await page.click(opt.id); steps.push('사유 ' + opt.t); break } }
  await sleep(600); t = await tree()
  if (dedUp(body0, body(t))) steps.push('공제 금액 표시 — 사람 확인')
  else {
    // 3) 최종 확인: 클릭 뒤 새로 생긴 정확한 글자 후보가 1개일 때만. 0개면 되읽기만(네이티브 confirm 이 이미 처리했을 수 있다), 2개 이상이면 중단
    const fin = await newExact(CONFIRM)
    if (fin.length === 1) {
      await page.click(fin[0].id); steps.push('확인 ' + fin[0].t); await sleep(1500); t = await tree()
      if (/하시겠습니까|할까요|하시겠어요/.test(body(t))) { const ok = await newExact(['확인']); if (ok.length === 1) { await page.click(ok[0].id); steps.push('확인창'); await sleep(1500) } }
    } else steps.push('확인 버튼 후보 ' + fin.length + '개 — 안 누름')
  }
}
// 4) 상세를 다시 읽어 after_state
for (const id of opened.splice(0)) { try { await tabs.close(id) } catch (e) {} }
await open('https://www.musinsa.com/order/order-detail/' + no)
try { await page.waitFor(/결제 정보|주문 상품|로그인/, 8000) } catch (e) {}
await sleep(800)
const c2 = classify(await tree(), await page.url())
R.after_state = c2.state
R.note = steps.join(' > ') + ' | 후: ' + noteOf(c2)
return done(R)
