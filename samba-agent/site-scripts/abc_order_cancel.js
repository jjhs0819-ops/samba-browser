// ABC마트 주문취소 — 2026-10-28 실측 실패(구매 프로필 jjhs0819 로그인 풀림). 상태 글자는 abc_order_detail 목록, 버튼 글자는 추정.
// 미확인 화면은 전부 unknown/failed 로 사람에게 넘긴다. 확인창·사유 화면 미확인.
// 인자 {source_order_no, profile, mode:'check'|'cancel', reason_text} · 반환 {source_order_no, login, found, items, state, buttons, clicked, after_state, note}
// mode=check 는 절대 누르지 않는다. mode=cancel 은 found·items==1·state==cancellable·buttons==1 일 때만 1번 누른다.
// 판정 규칙(RULES)은 samba_agent/ops/cancel_screen.py SITE_RULES 와 같은 값 — 바꾸면 둘 다 바꾼다.
const RULES = {"segment": ["", "결제 정보"], "items": "(?:입금대기|결제완료|상품준비중|배송준비중|배송중|배송완료|수령완료|취소완료|취소접수)", "buttons": ["주문취소", "취소신청"], "shipped": ["상품준비중", "배송준비중", "배송중", "배송완료", "수령완료", "픽업준비완료", "구매확정", "교환접수", "반품접수", "반품완료"], "already_cancelled": ["취소완료"], "cancel_pending": ["취소접수", "취소요청"], "cancellable": ["결제완료"]}
const CONFIRM = ["취소신청", "취소 신청", "신청하기"] // 최종 확인 버튼 후보(미확인 추정) — 정확히 1개일 때만 누른다
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
const elems = t => t.split('PAGE TEXT')[0].split('\n').map(l => l.match(/^\[(\d+)\] (\S+)(?: "([^"]*)")?/)).filter(Boolean).map(m => ({ id: +m[1], role: m[2], t: (m[3] || '').trim() }))
const body = t => nz((t.split('PAGE TEXT')[1] || '').replace(/^:/, ''))
// 정확한 글자의 button·link, 없으면 clickable(앱이 한 버튼을 두 번 보여 준다)
const exact = (t, labels) => { const es = elems(t).filter(e => labels.includes(e.t)); const s = es.filter(e => e.role !== 'clickable'); return s.length ? s : es }
const classify = (t, url) => {
  const b = body(t)
  const out = { login: !(/\/login/i.test(url) || /아이디 저장|로그인하시면/.test(b)), found: new RegExp('(?<![0-9A-Za-z])' + esc(no) + '(?![0-9A-Za-z])').test(b), items: 0, state: 'unknown', buttons: 0, seg: '' }
  if (!b) return out
  let seg = b
  if (RULES.segment[0]) { const m = seg.match(new RegExp(RULES.segment[0])); if (m) seg = seg.slice(m.index) }
  if (RULES.segment[1]) { const m = seg.match(new RegExp(RULES.segment[1])); if (m) seg = seg.slice(0, m.index) }
  const ir = new RegExp(RULES.items, 'g'); const im = [...seg.matchAll(ir)]
  out.items = /\((?!\?)/.test(RULES.items) ? (im[0] ? parseInt(im[0][1], 10) || 0 : 0) : im.length
  for (const st of ['shipped', 'already_cancelled', 'cancel_pending', 'cancellable']) if (RULES[st].some(w => seg.includes(w))) { out.state = st; break }
  out.buttons = exact(t, RULES.buttons).length
  out.seg = seg
  return out
}
const noteOf = c => '상태 ' + c.state + ' · 상품행 ' + c.items + ' · 버튼 ' + c.buttons
await open('https://abcmart.a-rt.com/mypage/order/read-order-detail?orderNo=' + no)
try { await page.waitFor(/결제 정보|주문내역이 없|로그인/, 10000) } catch (e) {}
await sleep(800)
let t = await tree()
const c = classify(t, await page.url())
Object.assign(R, { login: c.login, found: c.found, items: c.items, state: c.state, buttons: c.buttons, note: noteOf(c) })
if (mode !== 'cancel') return done(R)
if (!(c.login && c.found && c.items === 1 && c.state === 'cancellable' && c.buttons === 1)) return done({ ...R, note: '조건 미충족 — 누르지 않음: ' + noteOf(c) })
// 1) 취소 버튼 1개 클릭
await page.click(exact(t, RULES.buttons)[0].id)
R.clicked = true
try { await page.waitFor(/취소|사유/, 8000) } catch (e) {}
await sleep(1200)
t = await tree()
let b2 = body(t)
const steps = ['클릭']
// 공제·수수료 글자가 보이면 더 가지 않는다(사람 확인)
if (/공제|취소 수수료|위약금|차감/.test(b2)) { steps.push('공제 글자 보여 중단') }
else {
  // 2) 사유: '단순 변심' 계열 선택지가 보이면 고른다(select 는 글자로, 그 외는 클릭 1번)
  const variants = [reason, reason.replace(/\s/g, ''), '단순변심', '단순 변심', '구매 의사 취소', '고객 변심']
  const sel = elems(t).find(e => e.role === 'select')
  if (sel) { for (const v of variants) { try { await page.select(sel.id, v); steps.push('사유 ' + v); break } catch (e) {} } }
  else { const opt = elems(t).find(e => /^(radio|option|clickable|button|label)$/.test(e.role) && variants.includes(e.t)); if (opt) { await page.click(opt.id); steps.push('사유 ' + opt.t) } }
  await sleep(600); t = await tree(); b2 = body(t)
  if (/공제|취소 수수료|위약금|차감/.test(b2)) steps.push('공제 글자 보여 중단')
  else {
    // 3) 최종 확인 버튼: 정확한 글자 후보가 1개일 때만
    const fin = exact(t, CONFIRM)
    if (fin.length === 1) {
      await page.click(fin[0].id); steps.push('확인 ' + fin[0].t); await sleep(1500); t = await tree(); b2 = body(t)
      // 한 번 더 묻는 창(…하시겠습니까)에 '확인' 하나뿐이면 누른다
      if (/하시겠습니까|할까요|하시겠어요/.test(b2)) { const ok = exact(t, ['확인']); if (ok.length === 1) { await page.click(ok[0].id); steps.push('확인창'); await sleep(1500) } }
    } else steps.push('확인 버튼 ' + fin.length + '개 — 안 누름')
  }
}
// 4) 15초 안에 상세를 다시 읽어 after_state
for (const id of opened.splice(0)) { try { await tabs.close(id) } catch (e) {} }
await open('https://abcmart.a-rt.com/mypage/order/read-order-detail?orderNo=' + no)
try { await page.waitFor(/결제 정보|주문내역이 없|로그인/, 8000) } catch (e) {}
await sleep(800)
const c2 = classify(await tree(), await page.url())
R.after_state = c2.state
R.note = steps.join(' > ') + ' | 후: ' + noteOf(c2)
return done(R)
