import { expect, test, type Page } from '@playwright/test'

async function loginAndOpenPrompt(page: Page, username: string, password: string) {
  await page.goto(process.env.E2E_BASE_URL || 'http://127.0.0.1:8090')
  await page.getByPlaceholder('用户名').fill(username)
  await page.getByPlaceholder('密码').fill(password)
  await page.locator('form').getByRole('button', { name: '登录', exact: true }).click()
  await expect(page.getByText(username, { exact: true })).toBeVisible()
  await page.getByText(username, { exact: true }).click()
  await page.getByRole('button', { name: '管理后台' }).click()
  await page.getByRole('button', { name: /系统提示词/ }).click()
  await expect(page.getByRole('textbox', { name: '系统提示词内容' })).toBeVisible()
}

test.describe('@live 真实普通用户/管理员权限矩阵', () => {
  test('普通用户为只读且后端拒绝写请求', async ({ page }) => {
    const username = process.env.E2E_USERNAME
    const password = process.env.E2E_PASSWORD
    test.skip(!username || !password, '需要设置普通用户 E2E 凭据')
    await loginAndOpenPrompt(page, username!, password!)

    const editor = page.getByRole('textbox', { name: '系统提示词内容' })
    await expect(editor).toHaveAttribute('readonly', '')
    await expect(page.getByRole('button', { name: '保存修改' })).toHaveCount(0)
    const currentContent = await editor.inputValue()
    const status = await page.evaluate(async (content) => (await fetch('/api/system-prompt', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${localStorage.getItem('token')}` },
      body: JSON.stringify({ content }),
    })).status, currentContent)
    expect(status).toBe(403)
  })

  test('管理员可见共享配置写控件', async ({ page }) => {
    const username = process.env.E2E_ADMIN_USERNAME
    const password = process.env.E2E_ADMIN_PASSWORD
    test.skip(!username || !password, '需要设置管理员 E2E 凭据')
    await loginAndOpenPrompt(page, username!, password!)

    await expect(page.getByRole('textbox', { name: '系统提示词内容' })).not.toHaveAttribute('readonly', '')
    await expect(page.getByRole('button', { name: '保存修改' })).toBeVisible()
    await page.getByRole('button', { name: /知识库/ }).click()
    await expect(page.getByRole('button', { name: '新增条目' }).first()).toBeVisible()
    await page.getByRole('button', { name: /Skills/ }).click()
    await expect(page.getByRole('button', { name: /上传 ZIP/ }).first()).toBeVisible()
    await page.getByRole('button', { name: /^MCP/ }).click()
    await expect(page.getByRole('button', { name: '新建 MCP' }).first()).toBeVisible()
  })
})
