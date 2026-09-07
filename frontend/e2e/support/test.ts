import { test as base } from '@playwright/test'

export { expect } from '@playwright/test'

export function isExternalFontRequest(url: URL) {
  return url.protocol === 'https:' && ['fonts.googleapis.com', 'fonts.gstatic.com'].includes(url.hostname)
}

// Functional tests should not wait for third-party font/CDN availability. A
// stalled stylesheet can block page.goto('load') before assertions even run.
export const test = base.extend({
  page: async ({ page }, runTest) => {
    await page.route(isExternalFontRequest, (route) => route.abort())
    await runTest(page)
  },
})
