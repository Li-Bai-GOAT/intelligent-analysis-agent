import type { Page } from '@playwright/test'
import { expect, test } from './support/test'
import { installMockBackend, sse } from './support/mockBackend'

async function login(page: Page, username = 'user') {
  await page.goto('/')
  await page.getByPlaceholder('用户名').fill(username)
  await page.getByPlaceholder('密码').fill('e2e-password')
  await page.locator('form').getByRole('button', { name: '登录', exact: true }).click()
  await expect(page.getByText(username, { exact: true })).toBeVisible()
}

async function createSession(page: Page) {
  await page.getByTitle('新建对话').click()
  await expect(page.getByText('开始新的对话')).toBeVisible()
}

async function send(page: Page, message: string) {
  await page.getByRole('textbox', { name: '向 Data agent 提问' }).fill(message)
  await page.getByTitle('发送').click()
}

test('登录、创建会话并发送简单问题成功', async ({ page }) => {
  await installMockBackend(page)
  await login(page)
  await createSession(page)
  await send(page, '1 + 1 等于多少？')

  await expect(page.getByText('1 + 1 等于多少？')).toBeVisible()
  await expect(page.getByText('简单问题回答成功。')).toBeVisible()
  await expect(page.getByTitle('发送')).toBeVisible()
})

test('CSS 代码块保留选择器和属性的语法高亮', async ({ page }) => {
  await installMockBackend(page, {
    streamBodies: [sse(
      { type: 'text', content: '```css\n.example {\n  color: red;\n  padding: 12px;\n}\n```' },
      { type: 'end' },
    )],
  })
  await login(page)
  await createSession(page)
  await send(page, '展示 CSS 示例')

  const code = page.locator('.markdown-body code.language-css')
  await expect(code).toContainText('.example')
  for (const token of ['.example', 'color', 'padding']) {
    const highlighted = code.getByText(token, { exact: true })
    await expect(highlighted).toBeVisible()
    await expect(highlighted).toHaveAttribute('style', /color:/)
  }
  await expect(page.getByTitle('发送')).toBeVisible()
})

test('主对话页四处控件保留组件声明的内边距', async ({ page }, testInfo) => {
  await installMockBackend(page, {
    streamBodies: [sse(
      { type: 'thinking', content: '检查控件内边距。' },
      { type: 'text', content: '间距验证完成。' },
      { type: 'end' },
    )],
  })
  await login(page)
  await createSession(page)
  await send(page, '检查界面间距')
  await expect(page.getByText('间距验证完成。')).toBeVisible()
  await page.getByRole('button', { name: '文件', exact: true }).click()

  for (const name of ['计划', '文件', '终端']) {
    await expect(page.getByRole('button', { name, exact: true })).toHaveCSS('padding', '6px 12px')
  }
  for (const title of ['新建对话', '收缩', '下载全部(ZIP)', '刷新']) {
    await expect(page.getByTitle(title, { exact: true })).toHaveCSS('padding', '4px')
  }
  await expect(page.getByRole('button', { name: '思考过程', exact: true })).toHaveCSS('padding', '8px 12px')
  await expect(page.getByTitle('发送')).toBeVisible()
  await testInfo.attach('padding-restored-mock', {
    body: await page.screenshot({ path: testInfo.outputPath('padding-restored.png'), fullPage: true }),
    contentType: 'image/png',
  })
})

test('失败事件进入明确终态', async ({ page }) => {
  await installMockBackend(page, { streamBodies: [sse({ type: 'error', content: '模型服务不可用' })] })
  await login(page)
  await createSession(page)
  await send(page, '触发失败')

  await expect(page.getByText('[ERROR] 模型服务不可用')).toBeVisible()
  await expect(page.getByTitle('发送')).toBeVisible()
})

test('中断会调用后端取消并结束运行态', async ({ page }) => {
  const backend = await installMockBackend(page, {
    streamBodies: [sse({ type: 'tool_call', tool_id: 'tool-1', content: 'run_kuncode', message: '正在执行长任务' })],
  })
  await login(page)
  await createSession(page)
  await send(page, '执行长任务')

  await expect(page.getByTitle('中断')).toBeVisible()
  await page.getByTitle('中断').click()
  await expect(page.getByText(/\[CANCELLED\].*代理已中断/)).toBeVisible()
  await expect(page.getByTitle('发送')).toBeVisible()
  expect(backend.interruptCalls).toBe(1)
})

test('KunCode 预览提交确认协议', async ({ page }) => {
  const backend = await installMockBackend(page, {
    streamBodies: [sse(
      { type: 'plan_preview', preview_id: 'plan-1', name: '分析计划', subtasks: [{ name: '读取数据' }] },
      { type: 'kuncode_preview', preview_id: 'code-1', prompt: '生成 report.md' },
    )],
  })
  await login(page)
  await createSession(page)
  await send(page, '生成分析计划和文件')

  await expect(page.getByText('确认 KunCode 调用')).toBeVisible()
  await page.getByRole('button', { name: '执行', exact: true }).click()
  await expect.poll(() => backend.confirmations.length).toBe(1)
  expect(backend.confirmations[0]).toMatchObject({
    path: '/kuncode/session-e2e/confirm/code-1',
    body: { action: 'confirm', prompt: '生成 report.md' },
  })

})

test('计划预览可从恢复接口确认', async ({ page }) => {
  const backend = await installMockBackend(page, {
    pendingPreview: {
      has_pending: true,
      preview_type: 'plan',
      preview_id: 'plan-2',
      name: '恢复后的计划',
      subtasks: ['校验输入', '生成报告'],
    },
  })
  await login(page)
  await createSession(page)

  await expect(page.getByText('确认分析计划')).toBeVisible()
  await page.getByRole('button', { name: '计划', exact: true }).click()
  await expect(page.getByText('恢复后的计划')).toBeVisible()
  await expect(page.getByText('校验输入')).toBeVisible()
  await page.getByRole('button', { name: '确认计划', exact: true }).click()
  await expect.poll(() => backend.confirmations.length).toBe(1)
  expect(backend.confirmations[0]).toMatchObject({
    path: '/kuncode/session-e2e/plan/confirm/plan-2',
    body: { action: 'confirm', name: '恢复后的计划', subtasks: ['校验输入', '生成报告'] },
  })
})

test('SSE 断线后携带 Last-Event-ID 重连并完成', async ({ page }) => {
  const backend = await installMockBackend(page, {
    streamBodies: [
      sse({ type: 'text', content: '连接中断前的内容' }),
      'id: 2-0\ndata: {"type":"text","content":"重连成功"}\n\nid: 3-0\ndata: {"type":"end"}\n\n',
    ],
  })
  await login(page)
  await createSession(page)
  await send(page, '测试重连')

  await expect(page.getByText('重连成功')).toBeVisible()
  await expect.poll(() => backend.lastEventIds.length).toBeGreaterThanOrEqual(2)
  expect(backend.lastEventIds[1]).toBe('1-0')
})

test('生成文件可在文件面板预览和下载', async ({ page }) => {
  await installMockBackend(page, {
    streamBodies: [sse(
      { type: 'text', content: '文件已生成：report.md', generated_files: ['report.md'] },
      { type: 'end' },
    )],
    files: [{ name: 'report.md', path: 'report.md', type: 'file', size: 32 }],
  })
  await login(page)
  await createSession(page)
  await send(page, '生成报告文件')

  await expect(page.getByText('report.md', { exact: true })).toBeVisible()
  await page.getByText('report.md', { exact: true }).click()
  await expect(page.getByText('文件预览成功')).toBeVisible()
  const downloadPromise = page.waitForEvent('download')
  await page.getByTitle('下载文件').click()
  const download = await downloadPromise
  expect(download.suggestedFilename()).toBe('report.md')
})
