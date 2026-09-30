import { defineConfig } from '@playwright/test'
export default defineConfig({
  testDir:'./e2e', fullyParallel:false, workers:1, retries:0, timeout:30000,
  reporter:[['list'],['json',{outputFile:'../../Evidence/ci/playwright.json'}]],
  use:{baseURL:'http://127.0.0.1:8782', viewport:{width:1440,height:1050}, trace:'retain-on-failure', screenshot:'only-on-failure',
    launchOptions: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ? {executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE} : {}},
  webServer:{command:'python scripts/e2e_server.py',cwd:'../..',url:'http://127.0.0.1:8782/health',reuseExistingServer:false,timeout:30000},
})
