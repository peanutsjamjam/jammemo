import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  // Apache の UserDir 配下（http://peanutsjamjam.jp/~sugawara/jammemo/）で配信するため、
  // 生成されるアセットの参照パスをこのサブパス基準にする
  base: '/~sugawara/jammemo/',
  plugins: [react()],
})
