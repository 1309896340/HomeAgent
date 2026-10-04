import { fileURLToPath, URL } from 'node:url'
import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  // 读取 .env / .env.local 等文件中的环境变量（便于 docker 部署时覆盖）
  const env = loadEnv(mode, fileURLToPath(new URL('.', import.meta.url)), '')
  // 后端代理目标地址，默认 http://127.0.0.1:8100，可被环境变量覆盖
  const backendTarget = env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8100'
  // 开发服务器端口，可被环境变量覆盖
  const devPort = Number(env.VITE_DEV_PORT) || 5173

  return {
    plugins: [vue(), tailwindcss()],
    server: {
      port: devPort,
      proxy: {
        // 前端代码中统一使用相对路径 /api/xxx，由 dev server 代理到后端，避免 CORS
        '/api': {
          target: backendTarget,
          changeOrigin: true,
          // 剥离 /api 前缀：前端请求 /api/items → 后端 /items
          rewrite: (path) => path.replace(/^\/api/, ''),
        },
      },
    },
  }
})
