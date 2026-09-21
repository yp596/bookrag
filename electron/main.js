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
const ROOT = path.resolve(__dirname, '..')
const BACKEND_DIR = path.join(ROOT, 'backend')
const HEALTH_TIMEOUT_MS = 90000

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
  const candidates = [
    path.join(BACKEND_DIR, 'dist', 'rag-backend', 'rag-backend.exe'), // onedir
    path.join(BACKEND_DIR, 'dist', 'rag-backend.exe'),                // onefile
    path.join(BACKEND_DIR, 'dist', 'rag-backend', 'rag-backend'),     // onedir (posix)
  ]
  for (const exe of candidates) {
    if (fs.existsSync(exe)) return { cmd: exe, args: ['--port', String(port)] }
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

  backendProc = spawn(cmd, args, {
    cwd: BACKEND_DIR,
    windowsHide: true,
    env: {
      ...process.env,
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

  const distIndex = path.join(ROOT, 'frontend', 'dist', 'index.html')
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
