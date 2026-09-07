import { expect, test, isExternalFontRequest } from './support/test'
import { installMockBackend, sse } from './support/mockBackend'
import { runChatSmoke } from './support/chatSmoke'

test('外部字体请求无响应时仍可登录', async ({ page, context }) => {
  await installMockBackend(page)
  // Intentionally leave CDN requests pending. The shared page fixture must
  // intercept them before they reach this context-level network failure.
  let stalledFontRequests = 0
  await context.route(isExternalFontRequest, () => {
    stalledFontRequests += 1
  })

  await page.goto('/')
  await page.getByPlaceholder('用户名').fill('user')
  await page.getByPlaceholder('密码').fill('e2e-password')
  await page.locator('form').getByRole('button', { name: '登录', exact: true }).click()
  await expect(page.getByText('user', { exact: true })).toBeVisible()
  expect(stalledFontRequests).toBe(0)
})

test('模型回复超过 30 秒仍可完成并清理测试会话', async ({ page, baseURL }) => {
  const backend = await installMockBackend(page, {
    // Deliberately exceed the global test budget using the exact same
    // scenario and timeout setup as live-smoke, without a real model call.
    streamDelayMs: 35_000,
    streamBodies: [sse({ type: 'text', content: 'E2E_OK' }, { type: 'end' })],
  })

  await runChatSmoke(page, {
    url: baseURL!,
    username: 'user',
    password: 'e2e-password',
  })
  expect(backend.deletedSessionIds).toEqual(['session-e2e'])
})
