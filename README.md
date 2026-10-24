# 三臂凿岩台车 · 交互教学（3D）

基于 Three.js 的隧道施工机械交互式教学页面。黄蓝涂装、27 个可点击部件，支持爆炸图、凿岩演示、学习行为统计，前后端双模式（本地服务 API / 静态站点自动降级）。

## 在线访问

GitHub Pages：`https://zwx-hub.github.io/jumbo-drill-teaching/`

## 本地运行（完整前后端交互）

方式一：双击 `start_server.bat`

方式二：命令行

```
python server.py
```

启动后在浏览器打开 `http://127.0.0.1:8000`。此时页面自动进入「服务端模式」，学习数据（会话、部件点击、演示次数、学习时长）统一保存到 `learning_state.json`。

## 功能特性

- **3D 模型**：程序化建模，黄蓝涂装，含高空作业平台（升降柱 + 护栏 + 爬梯）、4 根稳定支腿、沿车架液压管线、浅灰隧道轮廓线，对应参考图细节
- **27 个部件**：车体系统 6 项 + 工作装置 3 臂 × 7 级细分（钻臂 → 基本臂 → 短臂 → T型梁 → 推进梁 → 凿岩机 → 钎杆钻头），点击模型或清单均可查看详情
- **真实教学参数**：DJ3G 钻臂、HC95SA 凿岩机（21 kW / 63 Hz）、推进梁（5250 mm / 23000 N）、作业平台（举升 13646 mm / 载重 400 kg）
- **交互视图**：爆炸图、凿岩演示动画、3D 标注开关、复位视角、移动端抽屉适配
- **学习资料面板**：技术参数 / 知识要点（结构原理、工作原理、装配要点、维护要点）/ 学习数据（统计卡片 + 部件点击排行）
- **前后端双模式**：服务端模式（本地 server.py）与本地模式（静态 / GitHub Pages 自动降级为浏览器本地存储）自动切换，页面右下角显示当前模式

## 架构说明

```
浏览器（index.html）
   │ 探测 GET /api/health
   ├── 成功 ──→ 服务端模式：数据/参数/知识来自 API，学习行为 POST 上报，
   │             统计由 server.py 统一持久化（learning_state.json）
   └── 失败 ──→ 本地模式：内嵌数据副本 + localStorage 记录学习行为
```

GitHub Pages 为纯静态托管，页面会自动降级为本地模式；代码中已预置与页面内嵌一致的服务端数据，两种模式体验一致。

## REST API（server.py）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 健康检查 |
| GET | `/api/parts` | 部件清单（27 项，服务端权威数据） |
| GET | `/api/params` | 技术参数（钻臂 / 凿岩机 / 推进梁 / 作业平台） |
| GET | `/api/knowledge` | 知识要点（结构 / 原理 / 装配 / 维护） |
| GET | `/api/interactions` | 学习数据统计 |
| POST | `/api/interactions` | 上报学习行为 `{action, partId?, ms?, ts?}` |

## 目录结构

```
jumbo-drill-teaching/
├── index.html           教学主页面（单文件自包含，Three.js 走 CDN）
├── server.py            本地教学服务（Python 标准库，零依赖）
├── start_server.bat     一键启动脚本
└── README.md
```

## 技术栈

- Three.js 0.147（jsDelivr CDN）+ OrbitControls
- 原生 JavaScript（无构建工具）
- Python 3 标准库 `http.server`
