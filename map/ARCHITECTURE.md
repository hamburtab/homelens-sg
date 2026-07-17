# 技术栈汇总

## 地图项目（Singapore Map）

| 层 | 选型 |
|---|---|
| 前端框架 | React + TypeScript |
| 构建工具 | Vite |
| 地图 | Leaflet + react-leaflet |
| 空间计算 | @turf/turf |
| 样式 | 纯 CSS |
| 后端 | 无（纯前端 SPA） |
| 数据库 | 无（数据为静态 JSON 文件） |

---

## TaskManager

| 层 | 选型 |
|---|---|
| 全栈框架 | Next.js (App Router) |
| 前端 | React + Tailwind CSS，SSR |
| 后端 | Next.js Route Handlers（同进程） |
| 数据库 | SQLite + Prisma ORM |
| 认证 | JWT |
| 样式 | Tailwind CSS |
| 进程管理 | systemd |
| Web 服务器 | nginx（反向代理 + 静态文件） |

---

## 部署

| 项目 | 值 |
|---|---|
| 服务器 | AWS EC2 (Amazon Linux) |
| Web 服务器 | nginx，域名 `zly0428.cn` |
| TaskManager | rsync + systemd 重启 |
| 地图 | rsync 到 nginx 静态目录 |
