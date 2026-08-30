import { expect, test } from '@playwright/test'

test('@live 真实服务登录、创建会话并发送简单问题', async ({ page }) => {
  const username = process.env.E2E_USERNAME
  const password = process.env.E2E_PASSWORD
  test.skip(!username || !password, '需要设置 E2E_USERNAME 和 E2E_PASSWORD')

  let sessionId: string | null = null
  try {
    await page.goto(process.env.E2E_BASE_URL || 'http://127.0.0.1:8090')
    await page.getByPlaceholder('用户名').fill(username!)
    await page.getByPlaceholder('密码').fill(password!)
    await page.locator('form').getByRole('button', { name: '登录', exact: true }).click()
    await expect(page.getByText(username!, { exact: true })).toBeVisible()

    const sessionResponse = page.waitForResponse((response) => (
      response.url().endsWith('/api/conversation/sessions') && response.request().method() === 'POST'
    ))
    await page.getByTitle('新建对话').click()
    sessionId = String((await (await sessionResponse).json() as { session_id: string }).session_id)
    await expect(page.getByText('开始新的对话')).toBeVisible()
    await page.getByRole('textbox', { name: '向 Data agent 提问' }).fill('请只回答：E2E_OK')
    await page.getByTitle('发送').click()
    await expect(page.locator('.markdown-body').getByText(/E2E_OK/)).toBeVisible({ timeout: 120_000 })
    await expect(page.getByTitle('发送')).toBeVisible({ timeout: 120_000 })
  } finally {
    if (sessionId) {
      await page.evaluate(async (id) => {
        const token = localStorage.getItem('token')
        await fetch(`/api/sessions/${id}`, { method: 'DELETE', headers: { Authorization: `Bearer ${token}` } })
      }, sessionId).catch(() => undefined)
    }
  }
})
