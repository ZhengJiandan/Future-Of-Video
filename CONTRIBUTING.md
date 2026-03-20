# Contributing

感谢你愿意为 `future of video` 贡献代码。

## 开始之前

- 先阅读 [README.md](/Users/zhenglei/git/future-of-video/README.md)
- 确认本地可以完成最小模式启动
- 新功能和较大改动，建议先开 Issue 讨论

## 开发原则

- 优先保持主链路可跑通
- 默认不要引入新的强依赖
- 面向真实用户的文案避免开发痕迹
- 不要提交真实密钥、测试账号、渲染产物或上传素材

## 分支与提交

- 从 `main` 拉新分支
- 分支命名建议：
  - `feat/<short-name>`
  - `fix/<short-name>`
  - `docs/<short-name>`
- 提交信息建议简洁明确，例如：
  - `feat: add minimal runtime mode`
  - `fix: prevent late character entry in shot splitting`
  - `docs: improve README for open source release`

## Pull Request 要求

- 说明改动目的
- 说明影响范围
- 说明验证方式
- 如果有 UI 改动，附截图或录屏
- 如果有接口改动，附请求/响应示例

## 本地验证

后端：

```bash
cd backend
python3 -m pytest -o addopts='' tests
python3 -m py_compile app/main.py
```

前端：

```bash
cd frontend
npm install
npm run build
```

## 文档要求

以下改动通常需要同步更新文档：

- 新增环境变量
- 新增运行模式
- 新增外部依赖
- 新增关键接口
- 改变启动方式或部署方式

## 不建议提交的内容

- `backend/.env`
- `uploads/` 或 `backend/uploads/` 下的内容
- 本地数据库文件
- 大体积测试媒体
- 带有真实凭据的 compose 或脚本配置
