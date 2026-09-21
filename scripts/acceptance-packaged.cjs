'use strict'

/**
 * 打包产物验收 E2E
 *
 * 直接启动 win-unpacked 里的真实 Electron 应用，走一遍用户主链路：
 * 建库 -> 导入文档 -> 提问 -> 校验引用来源。
 *
 * 关键点：必须在干净的 userData 目录下跑，否则会复用开发期的库，
 * 测不出「首次安装」路径上的问题（这正是之前漏掉数据目录 bug 的原因）。
 */

const { _electron: electron } = require(process.env.PW_PATH || 'playwright')
const path = require('node:path')
const fs = require('node:fs')
const os = require('node:os')

const APP = process.env.RAG_APP ||
  String.raw`D:\桌面\rag-release\win-unpacked\RAG知识库.exe`
const DOC = String.raw`D:\桌面\rag\doc\验收测试文档-售后服务政策.txt`
const USER_DATA = path.join(os.tmpdir(), `rag-accept-${Date.now()}`)

const results = []
function check(name, ok, detail = '') {
  results.push({ name, ok, detail })
  console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  — ' + detail : ''}`)
}

;(async () => {
  fs.mkdirSync(USER_DATA, { recursive: true })
  console.log(`应用: ${APP}`)
  console.log(`数据目录: ${USER_DATA}\n`)

  const app = await electron.launch({
    executablePath: APP,
    args: [`--user-data-dir=${USER_DATA}`],
    timeout: 120000,
  })

  const page = await app.firstWindow({ timeout: 120000 })
  await page.waitForLoadState('domcontentloaded')

  // 等后端就绪：界面会先显示启动中，就绪后才渲染主界面
  await page.waitForFunction(
    () => !document.body.innerText.includes('正在启动'),
    null, { timeout: 180000 },
  )
  await page.waitForTimeout(2000)

  const bodyText = await page.evaluate(() => document.body.innerText)
  check('V1 应用启动并渲染主界面',
    bodyText.includes('知识库'), bodyText.slice(0, 60).replace(/\n/g, ' '))

  // ---- 新建知识库（在知识库页）----
  await page.evaluate(() => { location.hash = '#/knowledge' })
  await page.waitForTimeout(1500)

  // 用 placeholder 定位：antd 的 a-input 会渲染成 input[type=text]，
  // 但页面上另有下拉筛选框，按 placeholder 锚定才唯一
  await page.getByRole('button', { name: /新建知识库/ }).first().click()
  const kbInput = page.getByPlaceholder('例如：产品手册、售后政策')
  await kbInput.waitFor({ timeout: 15000 })
  await kbInput.fill('验收知识库')
  await page.getByRole('button', { name: '创 建' }).click()
  await page.waitForTimeout(2500)

  const afterCreate = await page.evaluate(() => document.body.innerText)
  check('V2 新建知识库', afterCreate.includes('验收知识库'))

  // ---- 导入文档（走 input[type=file] 直接注入，避开系统文件框）----
  const chooser = page.locator('input[type="file"]').first()
  await chooser.setInputFiles(DOC)
  await page.waitForTimeout(12000)

  const afterUpload = await page.evaluate(() => document.body.innerText)
  const uploaded = /售后服务政策|验收测试文档/.test(afterUpload)
  check('V3 导入文档并切片', uploaded, uploaded ? '' : afterUpload.slice(0, 120).replace(/\n/g, ' '))

  // ---- 语义提问：BM25 单路必定落空，命中即证明向量一路工作 ----
  // 问答在对话页，先切回去；再选中刚建的知识库
  await page.evaluate(() => { location.hash = '#/chat' })
  await page.waitForTimeout(1500)
  const kbPicker = page.getByText('选择知识库').first()
  if (await kbPicker.count()) {
    await kbPicker.click()
    await page.waitForTimeout(800)
    await page.getByText('验收知识库').last().click()
    await page.waitForTimeout(1000)
  }

  /**
   * 提问并只取「本轮」回答。
   *
   * 不能读整页 innerText：历史轮次的回答会留在页面上，
   * 第三问的「资料中未提及。」会污染后续所有断言。
   * 这里记录发问前的消息条数，之后只读新增的最后一条。
   */
  const ask = async (q) => {
    const box = page.getByPlaceholder(/基于当前知识库提问/)
    const before = await page.evaluate(() => {
      const nodes = document.querySelectorAll('.thread > .row')
      return nodes.length
    })
    await box.click()
    await box.fill(q)
    await page.keyboard.press('Enter')
    // 等 AI 回复落地：新增节点中出现左侧气泡，且流式光标消失
    await page.waitForFunction(
      (n) => {
        const rows = [...document.querySelectorAll('.thread > .row')]
        const fresh = rows.slice(n)
        return fresh.some((r) => r.classList.contains('left'))
          && !document.querySelector('.thread .cursor')
      },
      before, { timeout: 90000 },
    ).catch(() => {})
    await page.waitForTimeout(3000)
    return page.evaluate((n) => {
      const rows = [...document.querySelectorAll('.thread > .row')]
      return rows.slice(n).filter((r) => r.classList.contains('left'))
        .map((e) => e.innerText).join('\n')
    }, before)
  }

  const a1 = await ask('满多少钱包邮？')
  check('V4 语义检索（融合生效）',
    !a1.includes('资料中未提及') && /包邮|99|九十九/.test(a1),
    a1.includes('资料中未提及') ? '回答未提及' : '已命中语义片段')

  const a2 = await ask('保修期是几年')
  check('V5 字面检索（精确串）',
    !a2.includes('资料中未提及') && /保修|年/.test(a2))

  const a3 = await ask('明天天气怎么样')
  check('V6 无关问题正确拒答',
    a3.includes('资料中未提及'))

  const a4 = await ask('退换货政策是什么')
  check('V7 多轮问答稳定',
    !a4.includes('资料中未提及') && /退换|退货|换货/.test(a4))

  // ---- 数据落盘位置 ----
  const dbPath = path.join(USER_DATA, 'data', 'rag.db')
  check('V8 数据落到 userData（未污染安装目录）',
    fs.existsSync(dbPath), dbPath)

  const appDirDb = path.join(path.dirname(APP), 'data')
  check('V9 安装目录未被写入数据',
    !fs.existsSync(appDirDb))

  await app.close()

  const failed = results.filter((r) => !r.ok)
  console.log(`\n${results.length - failed.length}/${results.length} 通过`)
  if (failed.length) {
    console.log('失败项: ' + failed.map((f) => f.name).join(', '))
    process.exit(1)
  }
})().catch((e) => {
  console.error('E2E 异常:', e.message)
  process.exit(2)
})
