# RAG 知识库

本地离线运行的文档问答工具。导入文档后，用自然语言提问，答案基于文档内容并附原文出处。

生成模型可选**完全本地运行**（数据不出本机）或接入云端 API。

## 功能

- 导入 TXT / Markdown / PDF / Word 文档，自动按小节切分成片段
- 中文混合检索（jieba + BM25 关键词 · bge-small-zh 向量语义 · RRF 融合），答案附带引用片段，可展开查看原文
- 流式输出，逐字返回
- 多知识库隔离，各自独立索引
- 本地 / 云端双模型模式，切换只需改配置
- 浅色 / 深色主题
- 数据存本地，重启不丢失

## 技术架构

```
Electron 主进程
├── 渲染进程：Vue 3 + Ant Design Vue
└── Python 后端：FastAPI（子进程，动态端口）
    └── 检索 → 拼装上下文 → 生成（本地 llama-server 或云端 API）
```

前端直接向 Python 后端发 HTTP/SSE 请求；Electron 主进程只负责拉起后端进程、分配空闲端口、退出时回收。

## 目录结构

```
rag/
├── backend/            Python FastAPI 服务
│   ├── api/            知识库 / 问答 / 设置接口
│   ├── core/           解析、切片、检索、LLM、流水线
│   ├── tests/          单元测试
│   ├── main.py         服务入口
│   └── rag-backend.spec    PyInstaller 打包配置
├── frontend/           Vue 3 前端
│   └── src/
│       ├── views/      对话 / 知识库 / 设置
│       ├── components/ 消息气泡、引用卡片、侧边栏
│       └── stores/     状态管理
├── electron/           Electron 壳
│   ├── main.js         主进程
│   └── preload.js      IPC 安全桥
├── scripts/            验收脚本
│   └── acceptance-packaged.cjs   打包产物端到端验收
└── doc/                需求与实施方案
```

## 测试

```bash
cd backend
.venv/Scripts/python -m unittest discover -s tests -v
```

覆盖容易被改错、且改错后**不会报错只会静默降级**的逻辑：
HF 环境变量的强制覆盖、向量模型的三态状态机、模型权重的进程内共享。

打包产物的端到端验收另见 `scripts/acceptance-packaged.cjs`，
它需要先构建出 `rag-release/win-unpacked`，验证的是真实安装形态下的用户主链路。

## 开发运行

需要 **Node.js** 与 **Python 3.11**。

**1. 后端**

```bash
cd backend
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt    # Windows
.venv/bin/pip install -r requirements.txt        # macOS / Linux
```

**嵌入模型**（约 91 MB，仅源码运行需要）

模型未进版本库，首次用到向量检索时会自动从镜像下载到 `backend/models/`：

```bash
cd backend
.venv/Scripts/python -c "from core.embedder import Embedder; Embedder().embed(['预热'])"
```

下载失败不影响启动——检索会自动退化为 BM25 单路，并在后端日志中打印原因。
若需离线部署，直接把 `backend/models/` 拷贝过去即可，打包流程也是这么做的。

**2. 前端**

```bash
cd frontend
npm install
npm run dev        # http://localhost:5178
```

浏览器里访问前端时，Vite 会把 `/api` 代理到 `http://127.0.0.1:8756`，所以还需手动启动后端：

```bash
cd backend
.venv/Scripts/python main.py --port 8756
```

**3. 桌面端**

```bash
cd electron
npm install
npm run dev        # 开发模式，加载 Vite 服务
npm start          # 加载 frontend/dist（需先 npm run build）
```

桌面端会自动拉起后端并分配空闲端口，无需手动启动。

**4. 本地生成模型（可选）**

本地模式需要一个 OpenAI 兼容的推理服务。以 llama.cpp 为例：

```bash
llama-server.exe -m models/MiniCPM5-1B-F16.gguf -c 4096 -ngl 99 --port 8080
```

受显存限制，4 GB 显卡建议用 1B–3B 量化模型。也可以在设置页切换到云端 API。

## 打包分发

**1. 打包后端**

```bash
cd backend
.venv/Scripts/pip install pyinstaller
.venv/Scripts/pyinstaller rag-backend.spec --noconfirm --distpath dist --workpath build
```

产物在 `backend/dist/rag-backend/`。

**2. 打包前端**

```bash
cd frontend
npm run build
```

**3. 打包桌面应用**

```bash
cd electron
npm run pack      # 只生成免安装目录，便于快速验证
npm run build     # 生成 NSIS 安装包
```

输出在 `rag-release/`。目标机器无需安装 Python 与 Node。

嵌入模型（`backend/models/`，约 91 MB）经 electron-builder 的 `extraResources` 一并打进安装包，
终端用户开箱即用、无需联网下载；主进程通过 `RAG_MODELS_DIR` 告知后端其位置。

> 改 `backend/rag-backend.spec` 的排除列表时要留意：`core/embedder.py` 里
> `fastembed` 是函数内延迟导入，静态分析看不到，依赖链上的包必须写进 `hiddenimports`。
> 漏了不会报错——向量检索会静默退化成 BM25 单路。

## 数据位置

| 运行方式 | 数据目录 |
|---|---|
| 源码运行 | `backend/data/` |
| 安装包 / 免安装版 | `%APPDATA%/rag-desktop/data/` |
| 由 Electron 拉起 | 主进程经 `RAG_DATA_DIR` 指定 |

存放 `rag.db`（知识库元数据与切片）与 `settings.json`（模型配置）。

> `settings.json` 中的云端 API Key 为明文存储，仅适合在本机使用。

## 当前限制

- 文档支持 TXT / Markdown / PDF / Word，暂不支持图片、表格与扫描件的结构化解析。
- 本地小模型（1B 级）适合文档抽取式问答，复杂推理能力有限。
- 检索未接 Rerank，长文档下排序精度仍有提升空间。

## 许可

MIT
