'use strict'

/**
 * Electron 主进程
 *
 * 职责：把 Python 后端当作 sidecar 子进程管理起来，让用户双击即可使用，
 * 不需要自己开命令行启动服务。
 *
 * 启动顺序：
 *   1. 取一个空闲端口（不能写死，避免与用户手动启动的实例冲突）
 *   2. 用该端口拉起后端进程
 *   3. 轮询 /api/health，就绪后再放行界面
 *   4. 窗口关闭 / 应用退出时回收后端进程
 */

const { app, BrowserWindow, ipcMain, shell } = require('electron')
const path = require('node:path')
const net = require('node:net')
const fs = require('node:fs')
const { spawn } = require('node:child_process')

const DEV = process.argv.includes('--dev')
const DEV_URL = process.env.RAG_DEV_URL || 'http://localhost:5178'
const HEALTH_TIMEOUT_MS = 90000

/**
 * 路径基准。
 *
 * 打包后代码跑在 app.asar 里，__dirname 指向 asar 内部而非磁盘真实目录，
 * 且 asar 里的 exe 无法被 spawn 执行，所以随包的后端必须解包到 resources/。
 * 开发期则仍按源码目录结构定位，两种形态用 app.isPackaged 区分。
 */
const ROOT = path.resolve(__dirname, '..')
const BACKEND_DIR = app.isPackaged
  ? path.join(process.resourcesPath, 'backend') // extraResources 投放位置
  : path.join(ROOT, 'backend')

/**
 * 用户数据根目录。装到 Program Files 后安装目录只读，且升级会覆盖，
 * 因此知识库与配置必须落到 Electron 的用户数据目录。
 *
 * 传的是「根」，不是「data 目录」——后端 core/config.py 会在其下自行拼 data/，
 * 与独立运行 exe 时的 %APPDATA%/rag-desktop 形态保持一致。
 */
const DATA_DIR = app.isPackaged ? app.getPath('userData') : BACKEND_DIR

/**
 * 模型目录（只读资源，随包分发）。
 *
 * 与数据目录相反：模型不该被用户改动，也不该跟着用户走，
 * 它属于安装包的一部分，因此放在 resources/backend/models。
 */
const MODELS_DIR = path.join(BACKEND_DIR, 'models')

/** 后端状态，渲染进程通过 IPC 查询与订阅 */
let backend = { status: 'starting', url: '', message: '' }
let backendProc = null
let mainWindow = null
let quitting = false

// ---------------------------------------------------------------- 后端进程

/** 向系统申请一个空闲端口：监听 0 拿到分配结果后立即释放 */
function findFreePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer()
    srv.unref()
    srv.on('error', reject)
    srv.listen(0, '127.0.0.1', () => {
      const { port } = srv.address()
      srv.close(() => resolve(port))
    })
  })
}

/** 解析后端启动方式：打包后优先用 PyInstaller 产物，开发期用 venv 解释器 */
function resolveBackendCommand(port) {
  const candidates = app.isPackaged
    ? [
        // extraResources 把 onedir 产物投放到 resources/backend/，
        // exe 与 _internal 是同级关系
        path.join(BACKEND_DIR, 'rag-backend.exe'),
        path.join(BACKEND_DIR, 'rag-backend', 'rag-backend.exe'),
      ]
    : [
        path.join(BACKEND_DIR, 'dist', 'rag-backend', 'rag-backend.exe'), // onedir
        path.join(BACKEND_DIR, 'dist', 'rag-backend.exe'),                // onefile
        path.join(BACKEND_DIR, 'dist', 'rag-backend', 'rag-backend'),     // onedir (posix)
      ]
  for (const exe of candidates) {
    if (fs.existsSync(exe)) return { cmd: exe, args: ['--port', String(port)] }
  }

  // 打包后没有 venv 可退，直接给出明确原因，避免用户看到一句含糊的启动失败
  if (app.isPackaged) {
    throw new Error(`未找到后端程序，安装包可能不完整：${candidates[0]}`)
  }

  const py =
    process.platform === 'win32'
      ? path.join(BACKEND_DIR, '.venv', 'Scripts', 'python.exe')
      : path.join(BACKEND_DIR, '.venv', 'bin', 'python')
  if (!fs.existsSync(py)) {
    throw new Error(`未找到 Python 解释器：${py}`)
  }
  return { cmd: py, args: [path.join(BACKEND_DIR, 'main.py'), '--port', String(port)] }
}

function startBackend(port) {
  const { cmd, args } = resolveBackendCommand(port)

  // 打包后 exe 所在目录只读，数据要落到用户目录
  fs.mkdirSync(DATA_DIR, { recursive: true })

  backendProc = spawn(cmd, args, {
    cwd: path.dirname(cmd),
    windowsHide: true,
    env: {
      ...process.env,
      // 指定数据目录，覆盖后端默认的「exe 同级」推导逻辑
      RAG_DATA_DIR: DATA_DIR,
      // 指定模型目录：打包后它是 resources/backend/models，
      // 与 exe 同级推导出的路径并不一致，必须显式传入
      RAG_MODELS_DIR: MODELS_DIR,
      // 本机提交内存常年吃紧，OpenBLAS 多线程分配会直接终止进程，必须限制线程数
      OPENBLAS_NUM_THREADS: '1',
      OMP_NUM_THREADS: '1',
      PYTHONUNBUFFERED: '1',
      PYTHONIOENCODING: 'utf-8',
    },
  })

  backendProc.stdout.on('data', (d) => process.stdout.write(`[backend] ${d}`))
  backendProc.stderr.on('data', (d) => process.stderr.write(`[backend] ${d}`))

  backendProc.on('error', (err) => {
    backendProc = null
    setBackend({ status: 'error', url: '', message: `无法启动后端：${err.message}` })
  })

  backendProc.on('exit', (code, signal) => {
    backendProc = null
    if (quitting) return
    setBackend({
      status: 'error',
      url: '',
      message: `后端进程意外退出（code=${code}，signal=${signal}）`,
    })
  })
}

/** 轮询健康接口，直到就绪或超时 */
async function waitForHealth(port, timeoutMs = HEALTH_TIMEOUT_MS) {
  const url = `http://127.0.0.1:${port}/api/health`
  const deadline = Date.now() + timeoutMs

  while (Date.now() < deadline) {
    if (!backendProc) throw new Error('后端进程已退出')
    try {
      const resp = await fetch(url, { signal: AbortSignal.timeout(2000) })
      if (resp.ok) return url.replace(/\/api\/health$/, '')
    } catch {
      // 端口尚未监听，继续等
    }
    await new Promise((r) => setTimeout(r, 300))
  }
  throw new Error('后端启动超时，请检查模型服务或依赖是否完整')
}

/** 结束后端进程。Windows 下 Python 可能带子进程，用 taskkill 连整棵树一起收 */
function stopBackend() {
  const proc = backendProc
  if (!proc) return
  backendProc = null
  try {
    if (process.platform === 'win32') {
      spawn('taskkill', ['/pid', String(proc.pid), '/T', '/F'], { windowsHide: true })
    } else {
      proc.kill('SIGTERM')
    }
  } catch (e) {
    console.error('[main] 回收后端进程失败：', e.message)
  }
}

// ---------------------------------------------------------------- 状态广播

function setBackend(next) {
  backend = next
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('backend:status', backend)
  }
}

// ---------------------------------------------------------------- 窗口

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1320,
    height: 860,
    minWidth: 1040,
    minHeight: 660,
    show: false,
    backgroundColor: '#f4f5f7',
    title: '本地知识库',
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  })

  // 等首帧渲染完再显示，避免白屏闪烁
  mainWindow.once('ready-to-show', () => mainWindow.show())
  mainWindow.on('closed', () => {
    mainWindow = null
  })

  // 站外链接交给系统浏览器，不在应用内打开
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url)
    return { action: 'deny' }
  })

  // 打包后前端产物由 extraResources 投放到 resources/frontend/dist
  // （electron-builder 的 files 不支持 ../ 跳出项目根，只能走 extraResources）；
  // 开发期仍从源码树读 frontend/dist
  const distIndex = app.isPackaged
    ? path.join(process.resourcesPath, 'frontend', 'dist', 'index.html')
    : path.join(ROOT, 'frontend', 'dist', 'index.html')
  if (DEV) {
    mainWindow.loadURL(DEV_URL)
  } else if (fs.existsSync(distIndex)) {
    mainWindow.loadFile(distIndex)
  } else {
    mainWindow.loadURL(
      'data:text/html;charset=utf-8,' +
        encodeURIComponent(
          '<body style="font-family:sans-serif;padding:40px">' +
            '<h3>未找到前端构建产物</h3>' +
            '<p>请先执行 <code>cd frontend &amp;&amp; npm run build</code>，' +
            '或用 <code>npm run dev</code> 以开发模式启动。</p></body>',
        ),
    )
  }
}

// ---------------------------------------------------------------- 生命周期

// 重复启动时聚焦已有窗口，避免跑出两个后端进程
if (!app.requestSingleInstanceLock()) {
  app.quit()
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore()
      mainWindow.focus()
    }
  })

  app.whenReady().then(async () => {
    ipcMain.handle('backend:info', () => backend)
    ipcMain.handle('shell:open', (_e, url) => shell.openExternal(url))

    let port
    try {
      port = await findFreePort()
      setBackend({ status: 'starting', url: `http://127.0.0.1:${port}`, message: '正在启动本地服务…' })
      startBackend(port)
    } catch (e) {
      setBackend({ status: 'error', url: '', message: e.message })
    }

    createWindow()

    if (port) {
      try {
        const url = await waitForHealth(port)
        setBackend({ status: 'ready', url, message: '' })
      } catch (e) {
        setBackend({ status: 'error', url: `http://127.0.0.1:${port}`, message: e.message })
      }
    }

    app.on('activate', () => {
      if (BrowserWindow.getAllWindows().length === 0) createWindow()
    })
  })

  app.on('window-all-closed', () => {
    // 桌面端约定：关掉窗口就退出，连带回收后端
    app.quit()
  })

  app.on('before-quit', () => {
    quitting = true
    stopBackend()
  })

  // 主进程崩溃或收到信号时也要回收，否则会留下孤儿 Python 进程
  process.on('exit', stopBackend)
  for (const sig of ['SIGINT', 'SIGTERM']) {
    process.on(sig, () => {
      quitting = true
      stopBackend()
      app.quit()
    })
  }
}
