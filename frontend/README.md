# WekToDo Frontend

Milestone 7 的最小 Vue 客户端，使用 Vue 3、TypeScript、Vite、Pinia 与 Ant Design Vue。

## 本地开发

先启动仓库根目录中的 FastAPI 服务，再执行：

```powershell
cd frontend
Copy-Item .env.example .env
npm install
npm run dev
```

开发服务器默认监听 `http://127.0.0.1:5173`，并将 `/api` 代理到 `VITE_API_PROXY_TARGET`。

## 验证

```powershell
npm run typecheck
npm run build
```
