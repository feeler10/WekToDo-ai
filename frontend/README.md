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

### 多轮修改联调验收

先保证 FastAPI 与 Redis 可用，并准备一个标题为“接水任务”的任务。在同一个页面会话中依次发送：

1. `修改接水任务`
2. `标题`
3. `改成每天早上接水`

前两轮应继续显示 Agent 追问且输入框可用；第三轮应出现修改确认卡。确认前刷新或查询任务时标题仍为“接水任务”，点击确认后才变为“每天早上接水”。浏览器 Network 面板中的三次 `/api/agent/chat` 请求必须使用相同 `thread_id`、各自不同的 `request_id`，确认请求使用返回的 `pending_action.id`。

该流程已有后端 HTTP 回归测试；前端当前不新增测试框架，继续以 `typecheck`、生产构建和上述联调步骤作为最小验收门禁。

### 刷新恢复

当前用户 ID 会保存在 `wektodo.active-user.v1`，每个用户当前使用的会话 ID 会保存在 `wektodo.active-conversation.v1:{user_id}`。消息正文不保存在浏览器中；页面启动时通过 `/api/agent/conversations/{conversation_id}` 从 Redis 恢复。

验收时可在参数澄清或待确认卡出现后直接刷新页面：历史消息和当前确认卡应恢复，线程短 ID 保持不变，继续输入或确认后不得产生重复记录。更换用户 ID 并离开输入框后，页面会切换到该用户自己的当前会话。

当前只维护一个活动会话指针，没有实现左侧对话列表、新建/切换/重命名/归档 UI；Redis 中已经保存对话元数据和用户级更新时间索引，后续可以在不改消息模型的情况下增加这些功能。
