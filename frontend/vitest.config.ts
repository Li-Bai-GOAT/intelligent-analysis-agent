import { defineConfig } from 'vitest/config'

// Unit tests cover the streaming state machine (SSE projection, tool merging,
// turn finalization). They deliberately run in the `node` environment: the
// modules under test are plain reducers plus a zustand store, so no DOM is
// needed and the suite stays fast enough to gate every PR.
export default defineConfig({
  test: {
    include: ['tests/unit/**/*.test.ts'],
    setupFiles: ['tests/unit/setup.ts'],
    environment: 'node',
    clearMocks: true,
    restoreMocks: true,
    reporters: process.env.CI ? ['default', 'junit'] : ['default'],
    outputFile: {
      junit: 'test-results/vitest-junit.xml',
    },
    coverage: {
      provider: 'v8',
      include: ['src/stores/conversationProjection.ts', 'src/stores/session.ts'],
      reporter: process.env.CI ? ['text', 'lcov'] : ['text'],
      reportsDirectory: 'coverage',
      // Thresholds sit slightly below the measured baseline (65/50/61/67) so they
      // act as a regression guard instead of a wall that blocks every PR. Raising
      // them is welcome; lowering them to make a PR green is not.
      thresholds: {
        statements: 60,
        branches: 45,
        functions: 55,
        lines: 62,
      },
    },
  },
})
