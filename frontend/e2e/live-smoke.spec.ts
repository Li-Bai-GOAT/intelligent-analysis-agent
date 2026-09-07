import { test } from './support/test'
import { runChatSmoke } from './support/chatSmoke'

test('@live 真实服务登录、创建会话并发送简单问题', async ({ page }) => {
  const username = process.env.E2E_USERNAME
  const password = process.env.E2E_PASSWORD
  test.skip(!username || !password, '需要设置 E2E_USERNAME 和 E2E_PASSWORD')

  await runChatSmoke(page, {
    url: process.env.E2E_BASE_URL || 'http://127.0.0.1:8090',
    username: username!,
    password: password!,
  })
})
