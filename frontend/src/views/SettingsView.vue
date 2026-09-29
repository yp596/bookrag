<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { message as antMessage } from 'ant-design-vue'
import {
  CloudServerOutlined,
  DesktopOutlined,
  ApiOutlined,
  SaveOutlined,
  ExperimentOutlined,
} from '@ant-design/icons-vue'
import { api } from '../api/client'
import { useAppStore } from '../stores/app'
import { useKbStore } from '../stores/kb'

const app = useAppStore()
const kb = useKbStore()

const form = reactive({
  llm_mode: 'local',
  local: { base_url: '', model: '' },
  cloud: { base_url: '', api_key: '', model: '' },
  top_k: 3,
  chunk_size: 800,
  chunk_overlap: 100,
  cross_rerank_enabled: false,
})

const loading = ref(true)
const saving = ref(false)
const testing = ref(false)
const testResult = ref(null)
const localModel = ref(null)

const isLocal = computed(() => form.llm_mode === 'local')
const active = computed(() => (isLocal.value ? form.local : form.cloud))

/**
 * 语义检索（向量一路）的运行状态。
 *
 * idle 表示模型尚未加载——正常情况下一问一答就会触发加载并转为 ready，
 * 所以这里不提示，避免刚装好就弹出无意义的警告。
 * 只有 failed 才需要告知用户：检索已退化为关键词单路，口语化提问会漏召回。
 */
const vectorState = computed(() => app.health?.vector?.state || 'idle')
const vectorTone = computed(() => {
  if (vectorState.value === 'ready') return 'on'
  if (vectorState.value === 'failed') return 'warn'
  return 'idle'
})
const vectorLabel = computed(() => ({
  ready: '已启用（语义 + 关键词）',
  failed: '已降级（仅关键词）',
}[vectorState.value] || '待加载'))

const vectorHint = computed(() => {
  const raw = app.health?.vector?.error || ''
  const lines = [
    '语义检索模型未能加载，当前仅用关键词匹配，口语化提问可能召回不到相关条款。',
  ]
  // 常见原因直接给可操作的解法，比抛原始堆栈有用
  if (/No module named/i.test(raw)) {
    lines.push('原因：程序缺少运行组件，建议重新安装。')
  } else if (/SSL|CERTIFICATE|Connection|Timeout|Read timed out/i.test(raw)) {
    lines.push('原因：模型下载失败，请检查网络后重启程序。')
  } else if (raw) {
    lines.push(`原因：${raw.slice(0, 160)}`)
  }
  return lines.join(' ')
})

onMounted(() => {
  load()
  // 运行状态里的知识库数量来自 /api/health，进页面时重新取一次，避免显示启动时的旧值
  app.checkBackend()
  api.localModel().then((d) => { localModel.value = d }).catch(() => { localModel.value = null })
})

const localModelLabel = computed(() => {
  if (!localModel.value) return '未检测到'
  if (localModel.value.serving) return '运行中'
  if (localModel.value.ready) return '已就绪（未启动）'
  return '缺失（二进制或模型不存在）'
})

async function load() {
  loading.value = true
  try {
    const data = await api.getSettings()
    form.llm_mode = data.llm_mode
    Object.assign(form.local, data.local)
    Object.assign(form.cloud, data.cloud)
    form.top_k = data.top_k
    form.chunk_size = data.chunk_size ?? 800
    form.chunk_overlap = data.chunk_overlap ?? 100
    form.cross_rerank_enabled = !!data.cross_rerank_enabled
  } catch (e) {
    antMessage.error(e.message)
  } finally {
    loading.value = false
  }
}

function payload() {
  return {
    llm_mode: form.llm_mode,
    local: { ...form.local },
    cloud: { ...form.cloud },
    top_k: form.top_k,
    chunk_size: form.chunk_size,
    chunk_overlap: form.chunk_overlap,
    cross_rerank_enabled: form.cross_rerank_enabled,
  }
}

async function save() {
  saving.value = true
  try {
    await api.saveSettings(payload())
    antMessage.success('配置已保存')
    await app.checkBackend()
  } catch (e) {
    antMessage.error(e.message)
  } finally {
    saving.value = false
  }
}


/** 先落盘再测连通，避免测的是旧配置 */
async function test() {
  testing.value = true
  testResult.value = null
  try {
    await api.saveSettings(payload())
    const res = await api.testSettings()
    testResult.value = res
    // 获取模型列表
    if (res.ok && form.cloud.base_url && form.cloud.api_key) {
      try {
        const modelsRes = await fetch(`${form.cloud.base_url}/models`, {
          headers: { Authorization: `Bearer ${form.cloud.api_key}` },
        })
        if (modelsRes.ok) {
          const modelsData = await modelsRes.json()
          const models = modelsData.data || []
          testResult.value = {
            ...res,
            models: models.map((m) => m.id),
          }
        }

const modelOptions = ref([])

watch(() => testResult.value?.models, (models) => {
  if (models && models.length) {
    modelOptions.value = models.map((m) => ({ label: m, value: m }))
  } else {
    modelOptions.value = []
  }
}, { immediate: true })

function onModelSearch(value) {
  // 搜索时过滤模型列表
  if (!testResult.value?.models?.length) return
  const filtered = testResult.value.models.filter((m) =>
    m.toLowerCase().includes(value.toLowerCase())
  )
  modelOptions.value = filtered.map((m) => ({ label: m, value: m }))
}
      } catch (e) {
        // 获取模型列表失败不影响连接测试结果
      }
    }
  } catch (e) {
    testResult.value = { ok: false, message: e.message }
  } finally {
    testing.value = false
    await app.checkBackend()
  }
}

// ---------- 主题自定义 ----------
const THEME_COLORS = [
  { name: '暖橙', value: '#f97316' },
  { name: '蓝色', value: '#4f6ef7' },
  { name: '绿色', value: '#22c55e' },
  { name: '紫色', value: '#8b5cf6' },
  { name: '红色', value: '#ef4444' },
  { name: '青色', value: '#06b6d4' },
]

const currentColor = ref(localStorage.getItem('rag-accent-color') || '#f97316')
const fontSize = ref(Number(localStorage.getItem('rag-font-size')) || 14)

function applyTheme() {
  document.documentElement.style.setProperty('--accent', currentColor.value)
  document.documentElement.style.setProperty('--accent-soft', `${currentColor.value}1a`)
  document.body.style.fontSize = `${fontSize.value}px`
  localStorage.setItem('rag-accent-color', currentColor.value)
  localStorage.setItem('rag-font-size', String(fontSize.value))
}

function saveTheme() {
  applyTheme()
  antMessage.success('主题已保存')
}

onMounted(() => {
  applyTheme()
})

// ---------- 数据备份/恢复 ----------
const backupLoading = ref(false)
const restoreLoading = ref(false)

async function handleBackup() {
  backupLoading.value = true
  try {
    const data = await api.backupAll()
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `rag-backup-${new Date().toISOString().slice(0, 10)}.json`
    a.click()
    URL.revokeObjectURL(url)
    antMessage.success('备份已导出')
  } catch (e) {
    antMessage.error(`备份失败：${e.message}`)
  } finally {
    backupLoading.value = false
  }
}

async function handleRestore() {
  const input = document.createElement('input')
  input.type = 'file'
  input.accept = '.json'
  input.onchange = async (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    restoreLoading.value = true
    try {
      const text = await file.text()
      const data = JSON.parse(text)
      const res = await api.restoreAll(data)
      antMessage.success(`已恢复 ${res.restored.kbs} 个知识库、${res.restored.docs} 个文档`)
      await app.checkBackend()
      await load()
    } catch (err) {
      antMessage.error(`恢复失败：${err.message}`)
    } finally {
      restoreLoading.value = false
    }
  }
  input.click()
}

</script>

<template>
  <div class="settings">
    <header class="bar">
      <span class="title">设置</span>
    </header>

    <div class="scroll">
      <div class="wrap" :class="{ dim: loading }">
        <!-- ---------- 生成模型 ---------- -->
        <section class="card">
          <div class="card-head">
            <ApiOutlined class="card-icon" />
            <div>
              <h3>生成模型</h3>
              <p class="muted">负责根据检索到的资料片段组织答案</p>
            </div>
          </div>

          <div class="card-body">
            <div class="mode">
              <button
                class="mode-item"
                :class="{ on: isLocal }"
                @click="form.llm_mode = 'local'"
              >
                <DesktopOutlined />
                <div>
                  <div class="mode-title">本地模型</div>
                  <div class="mode-desc muted">数据不出本机，需先启动本地模型服务</div>
                </div>
              </button>
              <button
                class="mode-item"
                :class="{ on: !isLocal }"
                @click="form.llm_mode = 'cloud'"
              >
                <CloudServerOutlined />
                <div>
                  <div class="mode-title">云端 API</div>
                  <div class="mode-desc muted">效果更好，需联网并填写 API Key</div>
                </div>
              </button>
            </div>

            <a-form layout="vertical" class="form">
              <a-form-item label="服务地址">
                <a-input
                  v-model:value="active.base_url"
                  :placeholder="isLocal ? 'http://127.0.0.1:8080/v1' : 'https://…/v1'"
                />
                <div class="tip muted">
                  {{ isLocal
                    ? '本地模型服务需提供 OpenAI 兼容接口'
                    : '填写服务商的 OpenAI 兼容端点，通常以 /v1 结尾' }}
                </div>
              </a-form-item>

              <a-form-item v-if="!isLocal" label="API Key">
                <a-input-password
                  v-model:value="form.cloud.api_key"
                  placeholder="sk-…"
                  autocomplete="off"
                />
                <div class="tip muted">仅保存在本机配置文件中，不会随文档上传</div>
              </a-form-item>

              <a-form-item label="模型名称">
                <a-select
                  v-model:value="active.model"
                  show-search
                  :placeholder="isLocal ? 'MiniCPM5-1B' : 'deepseek-v4.1-flash'"
                  :options="modelOptions"
                  :filter-option="false"
                  @search="onModelSearch"
                />
                <div v-if="testResult && testResult.models && testResult.models.length" class="model-list">
                  <div class="model-list-title">可用模型</div>
                  <div class="model-list-items">
                    <a-tag v-for="m in testResult.models" :key="m" class="model-tag">
                      {{ m }}
                    </a-tag>
                  </div>
                </div>
              </a-form-item>
            </a-form>

            <div class="actions">
              <a-button :loading="testing" @click="test">
                <template #icon><ExperimentOutlined /></template>
                测试连接
              </a-button>
              <a-button type="primary" :loading="saving" @click="save">
                <template #icon><SaveOutlined /></template>
                保存配置
              </a-button>
            </div>

            <a-alert
              v-if="testResult"
              class="result"
              :type="testResult.ok ? 'success' : 'error'"
              :message="testResult.ok ? '连接正常' : '连接失败'"
              :description="testResult.message"
              show-icon
            />
          </div>

        </section>


        <!-- ---------- 数据备份/恢复 ---------- -->
        <section class="card">
          <div class="card-head">
            <SaveOutlined class="card-icon" />
            <div>
              <h3>数据备份/恢复</h3>
              <p class="muted">导出或恢复知识库、文档、对话历史</p>
            </div>
          </div>
          <div class="card-body">
            <div class="actions">
              <a-button :loading="backupLoading" @click="handleBackup">
                <template #icon><SaveOutlined /></template>
                导出备份
              </a-button>
              <a-button :loading="restoreLoading" @click="handleRestore">
                <template #icon><ExperimentOutlined /></template>
                恢复备份
              </a-button>
            </div>
            <div class="tip muted">
              备份包含全部知识库、文档切片、对话历史。恢复会覆盖当前数据，请谨慎操作。
            </div>
          </div>
        </section>

        <!-- ---------- 检索设置 ---------- -->
        <!-- ---------- 检索 ---------- -->
        <section class="card">
          <div class="card-head">
            <DesktopOutlined class="card-icon" />
            <div>
              <h3>检索设置</h3>
              <p class="muted">控制送入模型的片段数量，以及新导入文档的切片方式</p>
            </div>
          </div>

          <div class="card-body">
            <a-form layout="vertical" class="form">
              <a-form-item :label="`引用片段数：${form.top_k}`">
                <a-slider v-model:value="form.top_k" :min="1" :max="10" :step="1" />
                <div class="tip muted">
                  片段越多，覆盖越全，但生成越慢、越容易夹带无关内容。建议 3～5。
                </div>
              </a-form-item>
              <a-form-item :label="`切片长度：${form.chunk_size} 字`">
                <a-slider v-model:value="form.chunk_size" :min="200" :max="2000" :step="50" />
                <div class="tip muted">
                  单个片段的字符上限。太小语义碎，太大易混入多主题。建议 500～1000。
                </div>
              </a-form-item>
              <a-form-item :label="`切片重叠：${form.chunk_overlap} 字`">
                <a-slider v-model:value="form.chunk_overlap" :min="0" :max="500" :step="10" />
                <div class="tip muted">
                  仅对保存之后导入的文档生效，已入库的文档不会重切。
                </div>
              </a-form-item>
              <a-form-item label="CrossEncoder 重排">
                <a-switch v-model:checked="form.cross_rerank_enabled" />
                <div class="tip muted">
                  可选第二阶段，首次开启需下载约 40MB 模型；失败自动回退加权精排。
                </div>
              </a-form-item>
            </a-form>
            <div class="actions">
              <a-button type="primary" :loading="saving" @click="save">
                <template #icon><SaveOutlined /></template>
                保存配置
              </a-button>
            </div>
          </div>
        </section>

        <!-- ---------- 主题自定义 ---------- -->
        <section class="card">
          <div class="card-head">
            <DesktopOutlined class="card-icon" />
            <div>
              <h3>主题自定义</h3>
              <p class="muted">选择主题色与字体大小</p>
            </div>
          </div>
          <div class="card-body">
            <div class="theme-section">
              <div class="theme-label">主题色</div>
              <div class="color-options">
                <button
                  v-for="c in THEME_COLORS"
                  :key="c.value"
                  class="color-btn"
                  :class="{ active: currentColor === c.value }"
                  :style="{ background: c.value }"
                  :title="c.name"
                  @click="currentColor = c.value; applyTheme()"
                />
              </div>
            </div>
            <div class="theme-section">
              <div class="theme-label">字体大小：{{ fontSize }}px</div>
              <a-slider v-model:value="fontSize" :min="12" :max="18" :step="1" @change="applyTheme" />
            </div>
            <div class="actions">
              <a-button type="primary" @click="saveTheme">
                <template #icon><SaveOutlined /></template>
                保存主题
              </a-button>
            </div>
          </div>
        </section>

        <!-- ---------- 运行状态 ---------- -->

        <!-- ---------- 关于 ---------- -->
        <section class="card">
          <div class="card-head">
            <DesktopOutlined class="card-icon" />
            <div>
              <h3>运行状态</h3>
              <p class="muted">后端服务与数据存放位置</p>
            </div>
          </div>
          <div class="card-body">
            <div class="kv">
              <span class="k">后端服务</span>
              <span class="v">
                <span class="dot" :class="{ on: app.online }" />
                {{ app.online ? '运行中' : '未连接' }}
              </span>
            </div>
            <div class="kv">
              <span class="k">知识库数量</span>
              <span class="v">{{ app.health?.knowledge_bases ?? '—' }}</span>
            </div>
            <div class="kv">
              <span class="k">当前模型</span>
              <span class="v">{{ app.health?.model ?? '—' }}</span>
            </div>
            <div class="kv">
              <span class="k">语义检索</span>
              <span class="v">
                <span class="dot" :class="{ on: vectorTone === 'on', warn: vectorTone === 'warn' }" />
                {{ vectorLabel }}
              </span>
            </div>
            <div class="kv">
              <span class="k">本地模型</span>
              <span class="v">
                <span class="dot" :class="{ on: localModel?.serving, warn: localModel && !localModel.ready }" />
                {{ localModelLabel }}
              </span>
            </div>
          </div>
          <!-- 向量模型不可用时给出可操作的原因，而不是让用户面对「回答变差」 -->
          <p v-if="vectorTone === 'warn'" class="vector-hint">
            {{ vectorHint }}
          </p>
        </section>

      </div>
    </div>
  </div>
</template>

<style scoped>
.settings {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}
.bar {
  padding: 14px 22px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-panel);
}
.title {
  font-size: 14px;
  font-weight: 600;
}
.scroll {
  flex: 1;
  overflow-y: auto;
  padding: 20px 22px 40px;
}
.wrap {
  max-width: 720px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
  transition: opacity 0.2s;
}
.wrap.dim {
  opacity: 0.5;
  pointer-events: none;
}

.card {
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--bg-panel);
  overflow: hidden;
  box-shadow: var(--shadow-sm);
}
.card-head {
  display: flex;
  gap: 11px;
  padding: 15px 18px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-code);
}
.card-icon {
  margin-top: 3px;
  font-size: 16px;
  color: var(--accent);
}
.card-head h3 {
  margin: 0 0 3px;
  font-size: 14px;
  font-weight: 600;
}
.card-head p {
  margin: 0;
  font-size: 12.5px;
}
.card-body {
  padding: 18px;
}

/* ---------- 模式切换 ---------- */
.mode {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
  margin-bottom: 20px;
}
.mode-item {
  display: flex;
  gap: 11px;
  padding: 13px 14px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--bg-panel);
  color: var(--text-2);
  font-family: inherit;
  font-size: 15px;
  text-align: left;
  cursor: pointer;
  transition: all 0.15s;
}
.mode-item:hover {
  border-color: var(--border-strong);
}
.mode-item.on {
  border-color: var(--accent);
  background: var(--accent-soft);
  color: var(--accent);
  box-shadow: 0 2px 8px rgba(249, 115, 22, 0.12);
}
.mode-title {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--text-1);
  margin-bottom: 3px;
}
.mode-item.on .mode-title {
  color: var(--accent);
}
.mode-desc {
  font-size: 11.5px;
  line-height: 1.5;
}

.form :deep(.ant-form-item) {
  margin-bottom: 16px;
}
.form :deep(.ant-form-item-label > label) {
  font-size: 13px;
}
.tip {
  margin-top: 5px;
  font-size: 11.5px;
  line-height: 1.6;
}

.actions {
  display: flex;
  gap: 10px;
  margin-top: 4px;
}
.result {
  margin-top: 16px;
}

/* ---------- 运行状态 ---------- */
.kv {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 9px 0;
  font-size: 13px;
}
.kv + .kv {
  border-top: 1px solid var(--border);
}
.k {
  color: var(--text-2);
}
.v {
  display: flex;
  align-items: center;
  gap: 7px;
  font-weight: 500;
}
.dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;

/* ---------- 临时测试 ---------- */
.direct-test {
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px dashed var(--border);
}
.direct-test-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-1);
  margin-bottom: 12px;
}
  background: var(--text-3);
}
.dot.on {
  background: #22c55e;
  box-shadow: 0 0 0 3px rgba(34, 197, 94, 0.16);
}
.dot.warn {
  background: #f59e0b;
  box-shadow: 0 0 0 3px rgba(245, 158, 11, 0.16);
}

.vector-hint {
  margin: 10px 0 0;
  padding: 8px 10px;
  border-radius: 8px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--text-2);
  background: rgba(245, 158, 11, 0.08);
  border-left: 2px solid #f59e0b;
}

/* ---------- 模型列表 ---------- */
.model-list {
  margin-top: 12px;
  padding: 12px;
  border-radius: 8px;
  background: var(--bg-panel);
  border: 1px solid var(--border);
}
.model-list-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-2);
  margin-bottom: 8px;
}
.model-list-items {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.model-tag {
  font-size: 11px;
}


/* ---------- 主题自定义 ---------- */
.theme-section {
  margin-bottom: 16px;
}
.theme-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-1);
  margin-bottom: 8px;
}
.color-options {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
.color-btn {
  width: 32px;
  height: 32px;
  border: 2px solid transparent;
  border-radius: 50%;
  cursor: pointer;
  transition: all 0.15s;
  padding: 0;
}
.color-btn:hover {
  transform: scale(1.1);
}
.color-btn.active {
  border-color: var(--text-1);
  box-shadow: 0 0 0 2px var(--bg-panel), 0 0 0 4px var(--accent);
}
</style>
