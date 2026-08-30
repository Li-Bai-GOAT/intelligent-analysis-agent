import { expect, test, type Page } from '@playwright/test'
import { installMockBackend } from './support/mockBackend'

async function loginAndOpenAdmin(page: Page, username: 'user' | 'admin') {
  await page.goto('/')
  await page.getByPlaceholder('用户名').fill(username)
  await page.getByPlaceholder('密码').fill('e2e-password')
  await page.locator('form').getByRole('button', { name: '登录', exact: true }).click()
  await page.getByText(username, { exact: true }).click()
  await page.getByRole('button', { name: '管理后台' }).click()
  await page.getByRole('button', { name: /系统提示词/ }).click()
  await expect(page.getByRole('textbox', { name: '系统提示词内容' })).toBeVisible()
}

test('普通用户只读且写接口返回 403', async ({ page }) => {
  const backend = await installMockBackend(page)
  await loginAndOpenAdmin(page, 'user')

  await expect(page.getByText('当前账号仅有查看权限，配置变更请联系管理员。')).toBeVisible()
  await expect(page.getByRole('textbox', { name: '系统提示词内容' })).toHaveAttribute('readonly', '')
  await expect(page.getByRole('button', { name: '保存修改' })).toHaveCount(0)
  await page.getByRole('button', { name: /知识库/ }).click()
  await expect(page.getByRole('button', { name: '新增条目' })).toHaveCount(0)
  await page.getByRole('button', { name: /Skills/ }).click()
  await expect(page.getByRole('button', { name: /上传 ZIP/ })).toHaveCount(0)
  await page.getByRole('button', { name: /^MCP/ }).click()
  await expect(page.getByRole('button', { name: '新建 MCP' })).toHaveCount(0)
  const status = await page.evaluate(async () => (await fetch('/api/system-prompt', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content: '越权修改' }),
  })).status)
  expect(status).toBe(403)
  expect(backend.writeStatuses).toEqual([403])
})

test('管理员可编辑并保存共享配置', async ({ page }) => {
  const backend = await installMockBackend(page)
  await loginAndOpenAdmin(page, 'admin')

  const editor = page.getByRole('textbox', { name: '系统提示词内容' })
  await expect(editor).not.toHaveAttribute('readonly', '')
  await editor.fill('管理员更新后的内容')
  await page.getByRole('button', { name: '保存修改' }).click()
  await expect(page.getByText('系统提示词已保存，后续 Agent 请求将使用新内容。')).toBeVisible()
  await page.getByRole('button', { name: /知识库/ }).click()
  await expect(page.getByRole('button', { name: '新增条目' }).first()).toBeVisible()
  await page.getByRole('button', { name: /Skills/ }).click()
  await expect(page.getByRole('button', { name: /上传 ZIP/ }).first()).toBeVisible()
  await page.getByRole('button', { name: /^MCP/ }).click()
  await expect(page.getByRole('button', { name: '新建 MCP' }).first()).toBeVisible()
  expect(backend.writeStatuses).toEqual([200])
})
