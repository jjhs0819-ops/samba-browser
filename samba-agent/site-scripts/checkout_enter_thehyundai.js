// 더현대Hi 주문서에서 현대백화점카드(등록 카드) 간편결제로 결제창을 연다(실결제 진입). 2026-10-28 첫 계약.
// 사용자 2026-10-28: 더현대는 현대백화점카드 4625 로만, 결제창은 '간편 결제'(등록 카드 비밀번호 앞 두 자리 — 키마스터 site 항목).
// 흐름: 주문서 대조 → 즉시할인·현대백화점 카드·등록 카드 확인 → 'N원 결제하기' → 팝업 hdpay.ehyundai.com → '간편 결제'
//  → 비밀번호 키패드(결제 에이전트가 fill_secret 으로 누른다). 이 스크립트는 비밀번호를 다루지 않는다.
// 안전장치: 시험(dryRun)은 결제하기 직전에서 멈춘다. 실결제는 expect(옵션)·amount·tab 이 없으면 누르지 않고,
//  결제 금액 > amount 거나 누르기 직전 되읽은 상품·금액이 바뀌면 멈춘다.
// args: card, profile, dryRun, expect{name,option,selected}, amount, tab, card_suffix · 반환 {ok,method,popup_url,total,order_tab,order_item,note}
const OF = /thehyundai\.com\/shop\/order(?:[?#]|$)/
const num = s => parseInt(String(s || '').replace(/[^\d]/g, ''), 10) || 0
const tree = async () => String((await page.get({})).tree || '')
const linesOf = tr => tr.split('PAGE TEXT')[0].split('\n').filter(l => /^\[\d+\]/.test(l))
const textOf = tr => (tr.split('PAGE TEXT:')[1] || '').replace(/\s+/g, ' ')
const norm = s => String(s || '').toLowerCase().replace(/[\s/·,()_-]+/g, '')
const cardSuffix = String(args.card_suffix || '4625')
const R = { ok: false, method: '현대백화점카드 간편결제', popup_url: null }
const fail = (note, x) => ({ ...R, note, ...(x || {}) })
const on = v => v != null && v !== false && !/^(false|0|no|)$/i.test(String(v).trim())
const dry = on(args.dryRun) || on(args.dry_run)
let e = args.expect
e = typeof e === 'string' ? { name: e } : e && typeof e === 'object' ? e : {}
const opt = String(e.selected || e.option || '').trim()
const amount = Math.round(Number(args.amount) || 0)
if (!dry && !opt) return fail('no expect', { why: 'need option' })
if (!dry && !(amount > 0)) return fail('no amount')
if (!dry && !args.tab) return fail('no tab')

const formInfo = async () => {
  const tr = await tree(), t = textOf(tr)
  const items = linesOf(tr).filter(l => /\] checkbox ".* [\d,원]+원 \d+개[ "]/.test(l)).map(l => l.match(/checkbox "([^"]*)"/)[1])
  return { tr, t, items, total: num((t.match(/결제 금액 ([\d,]+)원/) || [])[1]) }
}
const mismatch = f => {
  if (f.items.length !== 1) return `order items ${f.items.length}`
  const o = opt.replace(/\s*\/\s*/g, ' / ')
  if (opt && !/^단일$/.test(opt) && !norm(f.items[0]).includes(norm(o))) return `option ${opt} not in ${f.items[0].slice(0, 80)}`
  return null
}
const cand = (await tabs.list()).filter(t => OF.test(t.url || '') && (!args.tab || t.id === args.tab))
if (cand.length !== 1) return fail(cand.length ? 'order form ambiguous' : 'no order tab')
const tab = cand[0].id
await tabs.switch(tab)
if (!(await page.waitFor('결제하기', 8000))) return fail('order form not loaded')
let F = await formInfo()
const m = mismatch(F)
if (m) return fail('order form mismatch', { why: m })
Object.assign(R, { order_tab: tab, order_item: F.items[0].slice(0, 120), total: F.total })
if (!(F.total > 0)) return fail(`total ${F.total}`)
if (amount > 0 && F.total > amount) return fail(`total ${F.total} > expected ${amount}`)

// 즉시할인·결제수단·등록 카드
if (/체크박스 현대백화점카드/.test(F.t) && !/즉시할인 현대백화점카드/.test(F.t)) return fail('현대백화점카드 즉시할인 꺼짐')
const radio = linesOf(F.tr).find(l => /\] radio "현대백화점 카드"/.test(l))
if (!/value="on"/.test(radio || '')) return fail('현대백화점 카드 선택 안 됨')
const cardBtn = linesOf(F.tr).find(l => new RegExp(`\\] button "${cardSuffix}\\(`).test(l))
if (!cardBtn) return fail(`등록 카드 ${cardSuffix} 없음`)
await page.click(parseInt(cardBtn.slice(1))); await sleep(600)

const f2 = await formInfo(), m2 = mismatch(f2)
if (m2) return fail('order form mismatch', { why: 'before pay: ' + m2 })
if (f2.total !== F.total) return fail(`total changed ${F.total} -> ${f2.total}`)
const payLine = linesOf(f2.tr).find(l => /\] button "[\d,]+원 결제하기"$/.test(l))
if (!payLine) return fail('pay button not found')
if (num(payLine.match(/"([\d,]+)원/)[1]) !== f2.total) return fail('pay button amount != total')
if (dry) return { ...R, ok: true, dry: true, order_button: parseInt(payLine.slice(1)), note: 'dryRun: 결제하기 전 멈춤' }

const before = new Set((await tabs.list()).filter(t => t.kind === 'popup').map(t => t.id))
await page.click(parseInt(payLine.slice(1)))
let popup = null
for (let i = 0; i < 40 && !popup; i++) { await sleep(300); popup = (await tabs.list()).find(t => t.kind === 'popup' && !before.has(t.id) && /hdpay\.ehyundai\.com/.test(t.url || '')) || null }
if (!popup) return fail('no payment popup @ ' + String(await page.url()).replace(/^https?:\/\//, '').split('?')[0].slice(0, 60))
await tabs.switch(popup.id)
if (!(await page.waitFor('간편 결제', 10000))) return { ...R, ok: true, popup_url: popup.url, note: '결제창에 간편 결제 없음 — 화면 확인' }
const easy = linesOf(await tree()).find(l => /\] link "간편 결제/.test(l))
if (!easy) return { ...R, ok: true, popup_url: popup.url, note: '간편 결제 링크 못 찾음' }
await page.click(parseInt(easy.slice(1)))
await sleep(2500)
const cur = (await tabs.list()).filter(t => t.kind === 'popup' && !before.has(t.id))
const last = cur[cur.length - 1]
if (last) await tabs.switch(last.id)
return { ...R, ok: true, popup_url: last ? last.url : popup.url, note: '간편 결제 선택 — 키패드 대기' }
