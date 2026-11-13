const { defineConfig } = require('@playwright/test');
module.exports = defineConfig({
  testDir: __dirname,
  testMatch: 'mobile.spec.cjs',
  outputDir: '../../test-results',
  globalTimeout: 180000,
  timeout: 45000,
  retries: 0,
  workers: 1,
  reporter: [['list'], ['json', { outputFile: require('node:path').resolve(__dirname, '../../browser-results.json') }]],
  use: { browserName: 'chromium', trace: 'retain-on-failure' },
});
