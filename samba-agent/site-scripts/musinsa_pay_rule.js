// 무신사 결제 규칙 견적(2026-10-12 사용자 규칙). 결제하기는 절대 누르지 않는다.
// mode 'read': 무신사머니 줄 → 무신사페이(기본 카드) 줄 + 무신사 현대카드 청구할인·잔여 한도·청구 예상 + 즉시할인 타일 목록
// mode 'tile': args.tile 타일을 눌러 적용되는지(총액이 줄거나 '할인 적용 중'), 그때 수단·카드·총액
// 탭은 args.tab, 없으면 레인에 하나뿐인 무신사 주문서(여럿이면 멈춘다)
// 반환 read {ok, base_cost, money:{cost,balance,reward,points_used}, pay:{active_card,cost,reward,points_used,hyundai:{discount,remain,billed}}, tiles:[{name,amount}], cards, note}
// 반환 tile {ok, tile, usable, method, card, applied, cost, before, reward, note}
const nz = s => String(s || '').replace(/\s+/g, ' ').trim()
const num = s => parseInt(String(s || '').replace(/[^\d]/g, ''), 10) || 0
const OF = /musinsa\.com\/order\/order-form/
const get = async o => { for (let i = 0; i < 6; i++) { try { return (await page.get(o)).tree } catch (e) { await sleep(600) } } return '' }
const txt = async () => nz((await get({})).split('PAGE TEXT:')[1])
const notes = []
const ofs = (await tabs.list()).filter(t => OF.test(t.url || ''))
const tab = args.tab ? ofs.find(t => t.id === String(args.tab)) : ofs.length === 1 ? ofs[0] : null
if (!tab) return { ok: false, error: 'no-order-form', note: ofs.length ? `order forms ${ofs.length} open — pass args.tab` : 'no order form' }
await tabs.switch(tab.id)
try { await page.waitFor('총 결제 금액', 8000) } catch (e) {}

const totalOf = t => num((t.slice(t.lastIndexOf('결제 금액 상품 금액')).match(/총 결제 금액\s*(?:\d+%\s*)?([\d,]+)\s*원/) || [])[1])
const read = async () => {
  const tr = await get({ interactive: 1 }), box = tr.match(/textbox "보유 적립금 사용" value="([\d,]+)"/)
  const tx = await txt()
  const s = tx.slice(tx.lastIndexOf('결제 금액 상품 금액'))
  const tot = num((s.match(/총 적립 금액\s*([\d,]+)\s*원/) || [])[1]), rev = num((s.match(/후기 적립\s*최대\s*([\d,]+)\s*원/) || [])[1])
  return { tx, tr, cost: totalOf(tx), reward: Math.max(tot - rev, 0), points_used: box ? num(box[1]) : 0 }
}
const active = async () => nz((await get({ selector: '[class*=swiper-slide-active]' })).split('PAGE TEXT:')[1])
const cardName = s => nz(String(s || '').replace(/할인 적용 중/g, ' ').replace(/(신용카드|체크카드).*$/, ''))
const radioOf = (tree, nm) => { const l = tree.split('\n').find(x => /^\[\d+\] radio "/.test(x) && x.includes('] radio "' + nm)); return l ? parseInt(l.slice(1)) : 0 }
const radio = async nm => radioOf(await get({ interactive: 1 }), nm) || radioOf(String(await page.find(nm)), nm)
const pick = async nm => {
  const id = await radio(nm)
  if (!id) return false
  await page.click(id)
  try { await page.waitFor(nm + ' 결제', 3000) } catch (e) { await sleep(700) }
  return (await txt()).includes(nm + ' 결제')
}
const methodNow = tx => (tx.match(/(무신사머니|무신사페이|토스페이|카카오페이|페이코|네이버페이|KB Pay|삼성페이|카드|휴대폰|가상계좌) 결제 최대/) || [])[1] || null
const tilesOf = tx => {
  const sec = tx.slice(tx.indexOf('즉시 할인'), tx.indexOf('결제 수단'))
  return [...sec.matchAll(/-([\d,]+)원\s*(.+?)\s*\d+일 남음/g)].map(m => ({ name: nz(m[2]), amount: num(m[1]) }))
}

if ((args.mode || 'read') === 'read') {
  const out = { ok: false, base_cost: null, money: null, pay: null, tiles: [], cards: [], note: null }
  let r = await read()
  out.tiles = tilesOf(r.tx)
  if (await pick('무신사머니')) {
    r = await read()
    const sec = r.tx.slice(r.tx.indexOf('결제 수단'), r.tx.indexOf('결제 금액 상품 금액'))
    out.money = { cost: r.cost, balance: num((sec.match(/현재 보유 머니\s*([\d,]+)\s*원/) || [])[1]), reward: r.reward, points_used: r.points_used }
    out.base_cost = r.cost
  } else notes.push('무신사머니 없음')
  if (await pick('무신사페이')) {
    r = await read()
    const sec = r.tx.slice(r.tx.indexOf('결제 수단'), r.tx.indexOf('결제 금액 상품 금액'))
    out.cards = [...sec.matchAll(/([가-힣A-Za-z0-9 ]{2,30}?)\s*\((\d{3,4}\*?)\)\s*(?:할인 적용 중\s*)?(신용카드|체크카드)/g)].map(m => nz(m[1].split(/혜택 관리|혜택 받기|추가 할인|적립|일시불/).pop()))
    const ac = await active()
    const hy = { discount: 0, remain: null, billed: null }
    // 무신사 현대카드 혜택 칸은 그 카드가 선택돼 있을 때만 믿는다
    if (/무신사 현대/.test(ac)) {
      const hs = r.tx.slice(r.tx.indexOf('무신사 현대카드 혜택'))
      if (r.tx.includes('무신사 현대카드 혜택')) {
        hy.discount = num((hs.match(/청구 할인\s*-\s*([\d,]+)\s*원/) || [])[1])
        const rm = hs.match(/잔여 한도\s*([\d,]+)\s*원/)
        hy.remain = rm ? num(rm[1]) : null
      }
      const bl = r.tx.match(/([\d,]+)\s*원\s*청구 예상/)
      hy.billed = bl ? num(bl[1]) : null
    }
    out.pay = { active_card: cardName(ac) || null, cost: r.cost, reward: r.reward, points_used: r.points_used, hyundai: hy }
    if (!out.base_cost) out.base_cost = r.cost
  } else notes.push('무신사페이 없음')
  out.ok = !!out.base_cost
  out.note = notes.join('; ') || null
  return out
}

if (args.mode === 'tile') {
  const name = nz(args.tile)
  const out = { ok: false, tile: name, usable: false, method: null, card: null, applied: false, cost: null, before: null, reward: 0, note: null }
  if (!name) return { ...out, note: 'no tile' }
  const before = await read()
  out.before = before.cost
  const secOf = t => t.slice(t.indexOf('결제 수단'), t.indexOf('결제 금액 상품 금액'))
  const beforeMethod = methodNow(before.tx)
  const beforeApplied = /할인 적용 중/.test(secOf(before.tx))
  const line = before.tr.split('\n').find(x => /^\[\d+\] clickable "/.test(x) && x.includes('clickable "' + name + '"'))
  if (!line) return { ...out, note: 'tile not found' }
  await page.click(parseInt(line.slice(1)))
  await sleep(1500)
  const r = await read()
  out.cost = r.cost
  out.reward = r.reward
  out.method = methodNow(r.tx)
  const ac = await active()
  out.applied = /할인 적용 중/.test(secOf(r.tx))
  if (out.method === '무신사페이') out.card = cardName(ac) || null
  // 적용 판정은 '누르기 전과 달라졌는가'로만 본다 — 앞서 켠 농협 할인의 '할인 적용 중' 글자가 남아 있으면 비활성 카카오
  // 타일도 적용된 것으로 오판했다(실기 2026-10-12 23:48, 3건 pay_rule_stop)
  const methodChanged = !!out.method && out.method !== beforeMethod
  out.usable = (r.cost > 0 && before.cost > 0 && r.cost < before.cost) || methodChanged || (out.applied && !beforeApplied)
  out.ok = true
  return out
}
if (args.mode === 'select') {
  // 결제 직전: 무신사페이를 고르고, 타일이 있으면 그 즉시할인이 적용된 카드인지 맞춘다(결제하기는 누르지 않는다)
  const out = { ok: false, active: null, applied: false, note: null }
  if (!(await txt()).includes('무신사페이 결제') && !(await pick('무신사페이'))) return { ...out, note: '무신사페이 선택 실패' }
  let ac = await active()
  if (args.tile && !/할인 적용 중/.test(ac)) {
    const tr = await get({ interactive: 1 })
    const line = tr.split('\n').find(x => /^\[\d+\] clickable "/.test(x) && x.includes('clickable "' + nz(args.tile) + '"'))
    if (!line) return { ...out, active: ac, note: 'tile not found' }
    await page.click(parseInt(line.slice(1)))
    await sleep(1500)
    ac = await active()
  }
  out.active = ac
  out.applied = /할인 적용 중/.test(ac)
  out.ok = !!ac && (!args.pay_card || ac.includes(nz(args.pay_card))) && (!args.tile || out.applied)
  return out
}
return { ok: false, note: 'unknown mode ' + args.mode }
