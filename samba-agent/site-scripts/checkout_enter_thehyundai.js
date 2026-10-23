// 더현대Hi 주문서에서 현대백화점카드 간편결제를 고르고 필수 동의 뒤 '결제하기'로 결제 비밀번호 창을 연다(실결제 진입). 2026-10-23 초안.
// 비밀번호(카드 비밀번호 앞 2자리)는 여기서 넣지 않는다 — 결제 단계가 키마스터(thehyundai.com 계정 · 결제 비밀번호 site)로 앱이 넣는다.
// 안전장치: 시험(dryRun)은 결제하기 직전에서 멈춘다. 실결제는 expect·amount·tab 이 없으면 누르지 않고, 주문서 총액 > amount,
// 상품명·옵션 글자 불일치, 현대백화점카드 선택 실패, 누르기 직전 총액 변동이면 멈춘다. 로그인 뒤 화면은 실측 전(글자 대조만)
// args: card, profile, dryRun, expect{name,option,selected,product_no}, amount, tab · 반환 {ok,method,popup_url,keypad_in_tab,total,note,why}
const OF = /thehyundai\.com\/(?!mypage)[^?#]*order/i
const num = s => parseInt(String(s || '').replace(/[^\d]/g, ''), 10) || 0
function pe(t) { return t.split('PAGE TEXT')[0].split('\n').map(l => l.match(/^\[(\d+)\] (\S+)(?: "([^"]*)")?(.*)$/)).filter(Boolean).map(m => ({ id: +m[1], role: m[2], t: (m[3] || '').trim(), rest: m[4] || '' })) }
const Q = async q => pe((await page.get({ query: q })).tree)
const L = (a, f) => { const c = a.filter(f); return c.length ? c[c.length - 1] : null }
const text = async () => ((await page.get({})).tree.split('PAGE TEXT:')[1] || '').replace(/\s+/g, ' ')
const norm = s => String(s || '').toLowerCase().replace(/[\s/·,()_:\-]+/g, '')
const card = String(args.card || '')
const R = { ok: false, method: card || null, popup_url: null }
const fail = (note, x) => ({ ...R, note, ...(x || {}) })
const on = v => v != null && v !== false && !/^(false|0|no|)$/i.test(String(v).trim())
const dry = on(args.dryRun) || on(args.dry_run)
let e = args.expect
e = typeof e === 'string' ? { name: e } : e && typeof e === 'object' ? e : {}
const opt = String(e.selected || e.option || '').trim()
const GEN = new Set('매장정품 정품 남성 여성 남녀공용 공용 키즈 블랙 화이트 BLACK WHITE NIKE ADIDAS'.split(' '))
const words = String(e.name || '').split(/[\s/()[\],·_:-]+/).filter(w => w && !/^\d+$/.test(w) && !GEN.has(w.toUpperCase()) && ((/[가-힣]/.test(w) && w.length >= 2) || w.length >= 4))
const amount = Math.round(Number(args.amount) || 0)
if (!/현대백화점/.test(card)) return fail('unknown pay method: ' + card, { why: '더현대는 현대백화점카드 간편결제만' })
if (!dry && !(words.length || opt)) return fail('no expect')
if (!dry && !(amount > 0)) return fail('no amount')
if (!dry && !args.tab) return fail('no tab')
const list = await tabs.list()
const tab = list.find(t => args.tab ? t.id === args.tab : OF.test(t.url || ''))
if (!tab) return fail('no order tab')
if (!args.tab && list.filter(t => OF.test(t.url || '')).length > 1) return fail('order form ambiguous')
await tabs.switch(tab.id)
if (!OF.test(String(await page.url()))) return fail('order form mismatch', { why: 'tab is not an order form: ' + String(await page.url()).replace(/^https?:\/\//, '').slice(0, 60) })
await page.waitFor(/결제하기/, 10000); await sleep(600)
const grab = t => { const a = [...t.matchAll(/(?:최종\s*결제\s*금액|총\s*결제\s*금액|결제\s*예정\s*금액)\s*:?\s*([\d,]+)\s*원/g)]; const b = [...t.matchAll(/([\d,]+)\s*원\s*결제하기/g)]; return a.length ? num(a[a.length - 1][1]) : b.length ? num(b[b.length - 1][1]) : 0 }
function mismatch(t) {
  const n = norm(t)
  if (words.length && !words.some(w => n.includes(norm(w)))) return `name ${words.slice(0, 4)} not in order form`
  if (opt && !n.includes(norm(opt))) return `option ${opt} not in order form`
  return null
}
let t = await text()
let m = mismatch(t)
if (m) return fail('order form mismatch', { why: m })
// 결제수단: 현대백화점카드(간편결제). 없으면 '간편결제' 탭을 열고 다시 찾는다
async function payPick() {
  let c = (await Q('현대백화점카드')).filter(x => /현대백화점\s*카드/.test(x.t))
  if (!c.length) { const tb = L(await Q('간편결제'), x => /^간편\s*결제$/.test(x.t)); if (tb) { await page.click(tb.id); await sleep(800); c = (await Q('현대백화점카드')).filter(x => /현대백화점\s*카드/.test(x.t)) } }
  const hit = c.find(x => /간편/.test(x.t)) || c[c.length - 1]
  if (!hit) return null
  if (!/value="on"|selected|checked/.test(hit.rest)) { await page.click(hit.id); await sleep(1200) }
  return hit
}
const hit = await payPick()
if (!hit) return fail('pay method not found: 현대백화점카드 간편결제(실측 필요)')
R.method = '현대백화점카드 간편결제'
t = await text()
const total = grab(t)
Object.assign(R, { order_tab: tab.id, total })
if (!(total > 0)) return fail('total unreadable(실측 필요)')
if (amount > 0 && total > amount) return fail(`total ${total} > expected ${amount}`)
// 필수 동의 — '전체 동의' 를 누르고, 남은 필수 체크박스를 하나씩 켠다
const boxes = async () => (await Q('동의')).filter(x => /checkbox/.test(x.role))
if ((await boxes()).some(x => !/value="on"|checked/.test(x.rest))) {
  const all = L(await Q('동의'), x => /전체\s*동의|모두\s*동의/.test(x.t))
  if (all) { await page.click(all.id); await sleep(500) }
  for (const x of (await boxes()).filter(x => !/value="on"|checked/.test(x.rest) && !/선택|마케팅/.test(x.t))) { await page.click(x.id); await sleep(300) }
}
const left = (await boxes()).filter(x => !/value="on"|checked/.test(x.rest) && !/선택|마케팅/.test(x.t))
if (left.length) return fail('agreements not checked', { why: left.map(x => x.t).join(' | ').slice(0, 160) })
t = await text()
m = mismatch(t)
if (m) return fail('order form mismatch', { why: 'before pay: ' + m })
if (grab(t) !== total) return fail(`total changed ${total} -> ${grab(t)}`)
const pb = L(await Q('결제하기'), x => /button|link|clickable/.test(x.role) && /결제하기$/.test(x.t))
if (!pb) return fail('pay button not found')
if (dry) return { ...R, ok: true, dry: true, pay_button: pb.id, note: 'dryRun: 결제하기 전 멈춤' }
const before = new Set(list.filter(x => x.kind === 'popup').map(x => x.id))
await page.click(pb.id)
let popup = null, pw = false
for (let i = 0; i < 30 && !popup && !pw; i++) {
  await sleep(400)
  popup = (await tabs.list()).find(x => x.kind === 'popup' && !before.has(x.id)) || null
  if (!popup && i % 3 === 2) pw = /비밀번호/.test((await page.get({ query: '비밀번호' })).tree.split('PAGE TEXT')[0])
}
if (popup) return { ...R, ok: true, popup_url: popup.url, note: null }
if (pw) return { ...R, ok: true, keypad_in_tab: true, note: '비밀번호 창이 주문서 탭에 뜸' }
const ov = ((await page.get({})).tree.match(/OVERLAY: "([^"]{0,100})/) || [])[1]
return fail('no payment window', { why: ov ? '경고창: ' + ov : String(await page.url()).replace(/^https?:\/\//, '').split('?')[0].slice(0, 60) })
