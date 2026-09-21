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

const app = useAppStore()

const form = reactive({
  llm_mode: 'local',
  local: { base_url: '', model: '' },
  cloud: { base_url: '', api_key: '', model: '' },
  top_k: 3,
})

const loading = ref(true)
const saving = ref(false)
const testing = ref(false)
const testResult = ref(null)

const isLocal = computed(() => form.llm_mode === 'local')
const active = computed(() => (isLocal.value ? form.local : form.cloud))

onMounted(() => {
  load()
  // 运行状态里的知识库数量来自 /api/health，进页面时重新取一次，避免显示启动时的旧值
  app.checkBackend()
})

async function load() {
  loading.value = true
  try {
    const data = await api.getSettings()
    form.llm_mode = data.llm_mode
    Object.assign(form.local, data.local)
    Object.assign(form.cloud, data.cloud)
    form.top_k = data.top_k
  } catch (e) {
    antMessage.error(e.message)
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  try {
    await api.saveSettings({
      llm_mode: form.llm_mode,
      local: { ...form.local },
      cloud: { ...form.cloud },
      top_k: form.top_k,
    })
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
    await api.saveSettings({
      llm_mode: form.llm_mode,
      local: { ...form.local },
      cloud: { ...form.cloud },
      top_k: form.top_k,
    })
    const res = await api.testSettings()
    testResult.value = res
  } catch (e) {
    testResult.value = { ok: false, message: e.message }
  } finally {
    testing.value = false
    await app.checkBackend()
  }
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
                <a-input
                  v-model:value="active.model"
                  :placeholder="isLocal ? 'MiniCPM5-1B' : 'deepseek-v4.1-flash'"
                />
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

        <!-- ---------- 检索 ---------- -->
        <section class="card">
          <div class="card-head">
            <DesktopOutlined class="card-icon" />
            <div>
              <h3>检索设置</h3>
              <p class="muted">控制每次提问送入模型的资料片段数量</p>
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
            </a-form>
            <div class="actions">
              <a-button type="primary" :loading="saving" @click="save">
                <template #icon><SaveOutlined /></template>
                保存配置
              </a-button>
            </div>
          </div>
        </section>

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
          </div>
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
  border-radius: 11px;
  background: var(--bg-panel);
  overflow: hidden;
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
  border-radius: 10px;
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
  background: var(--text-3);
}
.dot.on {
  background: #22c55e;
  box-shadow: 0 0 0 3px rgba(34, 197, 94, 0.16);
}
</style>
