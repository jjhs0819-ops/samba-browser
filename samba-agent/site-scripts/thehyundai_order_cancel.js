// 더현대Hi 주문취소 — 2026-10-28 실측(profile buy-1): 배송완료 2건뿐. 결제완료·취소 화면·버튼 글자 미확인이라 자동취소 대상에서 뺄 것.
// 상세 주소 /mypage/order/detail?ordNo= (origin/feat/thehyundai-auto-purchase 의 thehyundai_order_detail 과 같다). 확인창·사유 화면 미확인.
// 인자 {source_order_no, profile, mode:'check'|'cancel', reason_text} · 반환 {source_order_no, login, found, items, state, buttons, clicked, after_state, note}
// mode=check 는 절대 누르지 않는다. mode=cancel 은 VERIFIED·login·found·items==1·state==cancellable·buttons==1 일 때만 1번 누른다.
// 판정 규칙(RULES·CONFIRM·VERIFIED)은 samba_agent/ops/cancel_screen.py 의 SITE_RULES·SITE_CONFIRM·SITE_VERIFIED 와 같은 값 — 드리프트 테스트가 비교한다.
// 앱은 자동화(full) 모드에서 페이지의 confirm() 을 자동 '예' 한다(src/main/browser/dialogs.ts) — 첫 클릭이 전체 가드 뒤라 사이트 확인창과 같은 뜻으로 본다(리뷰 1차 판정).
const RULES = {"segment": ["주문상품", "배송지"], "items": "원\\s*\\d+개", "buttons": ["주문취소", "주문 취소"], "shipped": ["배송완료", "배송중", "배송준비중", "상품준비중", "구매확정", "반품", "교환"], "already_cancelled": ["취소완료"], "cancel_pending": ["취소접수", "취소요청", "취소신청"], "cancellable": ["결제완료", "주문완료", "주문접수"]}
const CONFIRM = ["취소신청", "취소 신청", "신청하기"]
const VERIFIED = false
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
const noteOf = c => summary(c)
await open('https://hi.thehyundai.com/mypage/order/detail?ordNo=' + encodeURIComponent(no))
try { await page.waitFor(/결제정보|로그인/, 10000) } catch (e) {}
await sleep(800)
let t = await tree()
const c = classify(t, await page.url())
Object.assign(R, { login: c.login, found: c.found, items: c.items, state: c.state, buttons: c.buttons, note: noteOf(c) })
if (mode !== 'cancel') return done(R)
if (!VERIFIED) return done({ ...R, note: '조건 미충족 — 미검증 사이트: ' + summary(c) })
if (!(c.login && c.found && c.items === 1 && c.state === 'cancellable' && c.buttons === 1)) return done({ ...R, note: '조건 미충족 — 누르지 않음: ' + noteOf(c) })
// 클릭 전 요소·본문 스냅샷 — 그 뒤 '새로 나타난' 요소·글자만 본다(확인 버튼 탐색이 페이지 전체로 번지지 않게)
const before = new Set(elems(t).map(e => e.key))
const beforeWords = new Set(body(t).split(' '))
// 1) 취소 버튼 1개 클릭(여기까지가 전체 가드)
await page.click(exact(elems(t), RULES.buttons)[0].id)
R.clicked = true
try { await page.waitFor(/취소|사유/, 8000) } catch (e) {}
await sleep(1200)
t = await tree()
const fresh = () => elems(t).filter(e => !before.has(e.key))
const freshText = () => body(t).split(' ').filter(w => !beforeWords.has(w)).join(' ')
const steps = ['클릭']
const bad = s => /공제|취소 수수료|위약금|차감/.test(s)
if (!fresh().length && !freshText()) steps.push('새 화면 없음')
else if (bad(freshText())) steps.push('공제 글자 보여 중단')
else {
  // 2) 사유: 새로 나타난 select 는 글자로, 새 라디오/버튼이면 1클릭
  const variants = [reason, reason.replace(/\s/g, ''), '단순변심', '단순 변심', '구매 의사 취소', '고객 변심']
  const sel = fresh().find(e => e.role === 'select')
  if (sel) { for (const v of variants) { try { await page.select(sel.id, v); steps.push('사유 ' + v); break } catch (e) {} } }
  else { const opt = fresh().find(e => /^(radio|option|clickable|button|label)$/.test(e.role) && variants.includes(e.t)); if (opt) { await page.click(opt.id); steps.push('사유 ' + opt.t) } }
  await sleep(600); t = await tree()
  if (bad(freshText())) steps.push('공제 글자 보여 중단')
  else {
    // 3) 최종 확인: 새 요소 중 정확한 글자 후보가 1개일 때만. 0개면 되읽기만(네이티브 confirm 이 이미 처리했을 수 있다), 2개 이상이면 중단
    const fin = exact(fresh(), CONFIRM)
    if (fin.length === 1) {
      await page.click(fin[0].id); steps.push('확인 ' + fin[0].t); await sleep(1500); t = await tree()
      if (/하시겠습니까|할까요|하시겠어요/.test(freshText())) { const ok = exact(fresh(), ['확인']); if (ok.length === 1) { await page.click(ok[0].id); steps.push('확인창'); await sleep(1500) } }
    } else steps.push('확인 버튼 후보 ' + fin.length + '개 — 안 누름')
  }
}
// 4) 상세를 다시 읽어 after_state
for (const id of opened.splice(0)) { try { await tabs.close(id) } catch (e) {} }
await open('https://hi.thehyundai.com/mypage/order/detail?ordNo=' + encodeURIComponent(no))
try { await page.waitFor(/결제정보|로그인/, 8000) } catch (e) {}
await sleep(800)
const c2 = classify(await tree(), await page.url())
R.after_state = c2.state
R.note = steps.join(' > ') + ' | 후: ' + noteOf(c2)
return done(R)
