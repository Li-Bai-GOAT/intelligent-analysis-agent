import type { Page } from '@playwright/test'
import { expect, test } from './test'

const MODEL_REPLY_TIMEOUT = 120_000

export async function runChatSmoke(
  page: Page,
  credentials: { url: string; username: string; password: string },
) {
  // Assertion timeouts do not extend the enclosing 30s test budget. Reserve
  // another minute for login/session setup and cleanup, only for model smoke.
  test.setTimeout(MODEL_REPLY_TIMEOUT + 60_000)

  let sessionId: string | null = null
  try {
    await page.goto(credentials.url)
    await page.getByPlaceholder('用户名').fill(credentials.username)
    await page.getByPlaceholder('密码').fill(credentials.password)
    await page.locator('form').getByRole('button', { name: '登录', exact: true }).click()
    await expect(page.getByText(credentials.username, { exact: true })).toBeVisible()

    const sessionResponse = page.waitForResponse((response) => (
      response.url().endsWith('/api/conversation/sessions') && response.request().method() === 'POST'
    ))
    await page.getByTitle('新建对话').click()
    sessionId = String((await (await sessionResponse).json() as { session_id: string }).session_id)
    await expect(page.getByText('开始新的对话')).toBeVisible()
    await page.getByRole('textbox', { name: '向 Data agent 提问' }).fill('请只回答：E2E_OK')
    await page.getByTitle('发送').click()
    // Reply and terminal UI state share one 120s deadline. Check terminal
    // state after the reply, without granting another full 120s window.
    const replyDeadline = Date.now() + MODEL_REPLY_TIMEOUT
    await expect(page.locator('.markdown-body').getByText(/E2E_OK/)).toBeVisible({ timeout: MODEL_REPLY_TIMEOUT })
    await expect(page.getByTitle('发送')).toBeVisible({ timeout: Math.max(1, replyDeadline - Date.now()) })
  } finally {
    if (sessionId) {
      await page.evaluate(async (id) => {
        const token = localStorage.getItem('token')
        await fetch(`/api/sessions/${id}`, { method: 'DELETE', headers: { Authorization: `Bearer ${token}` } })
      }, sessionId).catch(() => undefined)
    }
  }
}
