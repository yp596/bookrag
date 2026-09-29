<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Modal, message as antMessage } from 'ant-design-vue'
import {
  InboxOutlined,
  FileTextOutlined,
  FilePdfOutlined,
  FileWordOutlined,
  FileExcelOutlined,
  FilePptOutlined,
  FileMarkdownOutlined,
  DeleteOutlined,
  PlusOutlined,
  MessageOutlined,
  LinkOutlined,
  SearchOutlined,
  DownloadOutlined,
  UploadOutlined,
} from '@ant-design/icons-vue'
import { useKbStore } from '../stores/kb'
import { api } from '../api/client'

const kb = useKbStore()
const router = useRouter()


const uploading = ref(false)
const progress = ref(0)
const uploadingName = ref('')
const creating = ref(false)
const newName = ref('')
const fetchUrl = ref('')
const fetching = ref(false)
const batchUrls = ref('')
const batchFetching = ref(false)
const showBatchUrl = ref(false)

// ---------- 爬取配置 ----------
const fetchConfigUrl = ref('')
const fetchConfigDepth = ref(2)
const fetchConfigMaxPages = ref(50)
const fetchConfigExclude = ref('')
const showFetchConfig = ref(false)
const recursiveFetching = ref(false)

async function submitRecursiveFetch() {
  const url = fetchConfigUrl.value.trim()
  if (!url || recursiveFetching.value) return
  if (!kb.currentId) {
    antMessage.warning('请先创建或选择知识库')
    return
  }
  recursiveFetching.value = true
  try {
    const res = await api.recursiveFetch(kb.currentId, {
      url,
      max_depth: fetchConfigDepth.value,
      max_pages: fetchConfigMaxPages.value,
      exclude_patterns: fetchConfigExclude.value.split('\n').map(s => s.trim()).filter(Boolean),
    })
    if (res.imported > 0) {
      antMessage.success(`成功爬取 ${res.imported} 个页面${res.failed > 0 ? `，失败 ${res.failed} 个` : ''}`)
      await kb.refreshDocs()
    } else {
      antMessage.error(`全部失败：${res.errors.join('；')}`)
    }
    if (res.errors.length > 0 && res.imported > 0) {
      antMessage.warning(`部分失败：${res.errors.join('；')}`)
    }
  } catch (e) {
    antMessage.error(`爬取失败：${e.message}`)
  } finally {
    recursiveFetching.value = false
  }
}

// ---------- 定时爬取 ----------
const scheduleUrl = ref('')
const scheduleFrequency = ref('daily')
const scheduleLoading = ref(false)
const schedules = ref([])
const showSchedule = ref(false)

async function submitSchedule() {
  const url = scheduleUrl.value.trim()
  if (!url || scheduleLoading.value) return
  if (!kb.currentId) {
    antMessage.warning('请先创建或选择知识库')
    return
  }
  scheduleLoading.value = true
  try {
    await api.createCrawlSchedule(kb.currentId, {
      url,
      frequency: scheduleFrequency.value,
    })
    antMessage.success('定时爬取任务已创建')
    scheduleUrl.value = ''
    await loadSchedules()
  } catch (e) {
    antMessage.error(`创建失败：${e.message}`)
  } finally {
    scheduleLoading.value = false
  }
}

async function loadSchedules() {
  if (!kb.currentId) return
  try {
    const res = await api.listCrawlSchedules(kb.currentId)
    schedules.value = res.schedules || []
  } catch (e) {
    antMessage.error(`加载失败：${e.message}`)
  }
}

async function deleteSchedule(scheduleId) {
  try {
    await api.deleteCrawlSchedule(kb.currentId, scheduleId)
    antMessage.success('已删除')
    await loadSchedules()
  } catch (e) {
    antMessage.error(`删除失败：${e.message}`)
  }
}

// ---------- 增量爬取 ----------
const incrementalUrl = ref('')
const incrementalFetching = ref(false)
const showIncremental = ref(false)

async function submitIncrementalFetch() {
  const url = incrementalUrl.value.trim()
  if (!url || incrementalFetching.value) return
  if (!kb.currentId) {
    antMessage.warning('请先创建或选择知识库')
    return
  }
  incrementalFetching.value = true
  try {
    const res = await api.incrementalFetch(kb.currentId, { url })
    if (res.imported > 0) {
      antMessage.success(`成功爬取 ${res.imported} 个页面${res.failed > 0 ? `，失败 ${res.failed} 个` : ''}`)
      await kb.refreshDocs()
    } else {
      antMessage.error(`全部失败：${res.errors.join('；')}`)
    }
  } catch (e) {
    antMessage.error(`爬取失败：${e.message}`)
  } finally {
    incrementalFetching.value = false
  }
}

// ---------- Agent 任务面板 ----------
const agentTaskTitle = ref('')
const agentTaskDesc = ref('')
const agentTaskLoading = ref(false)
const agentTasks = ref([])
const showAgentTask = ref(false)

async function submitAgentTask() {
  const title = agentTaskTitle.value.trim()
  if (!title || agentTaskLoading.value) return
  if (!kb.currentId) {
    antMessage.warning('请先创建或选择知识库')
    return
  }
  agentTaskLoading.value = true
  try {
    await api.createAgentTask(kb.currentId, {
      title,
      description: agentTaskDesc.value,
    })
    antMessage.success('任务已创建')
    agentTaskTitle.value = ''
    agentTaskDesc.value = ''
    await loadAgentTasks()
  } catch (e) {
    antMessage.error(`创建失败：${e.message}`)
  } finally {
    agentTaskLoading.value = false
  }
}

async function loadAgentTasks() {
  if (!kb.currentId) return
  try {
    const res = await api.listAgentTasks(kb.currentId)
    agentTasks.value = res.tasks || []
  } catch (e) {
    antMessage.error(`加载失败：${e.message}`)
  }
}

async function executeTask(taskId) {
  try {
    await api.executeAgentTask(kb.currentId, taskId)
    antMessage.success('任务执行完成')
    await loadAgentTasks()
  } catch (e) {
    antMessage.error(`执行失败：${e.message}`)
  }
}

async function deleteTask(taskId) {
  try {
    await api.deleteAgentTask(kb.currentId, taskId)
    antMessage.success('已删除')
    await loadAgentTasks()
  } catch (e) {
    antMessage.error(`删除失败：${e.message}`)
  }
}

// ---------- 文档搜索过滤 ----------
// ---------- 标签筛选 ----------
const selectedTags = ref([])
const allTags = computed(() => {
  const tags = new Set()
  for (const doc of kb.docs) {
    if (doc.tags) {
      for (const tag of doc.tags.split(',')) {
        const t = tag.trim()
        if (t) tags.add(t)
      }
    }
  }
  return Array.from(tags).sort()
})

function toggleTagFilter(tag) {
  const idx = selectedTags.value.indexOf(tag)
  if (idx >= 0) {
    selectedTags.value.splice(idx, 1)
  } else {
    selectedTags.value.push(tag)
  }
}

// ---------- 文档搜索过滤 ----------
const docSearchQuery = ref('')
const filteredDocs = computed(() => {
  let result = kb.docs
  // 标签筛选
  if (selectedTags.value.length) {
    result = result.filter(d => {
      if (!d.tags) return false
      const docTags = d.tags.split(',').map(t => t.trim())
      return selectedTags.value.some(t => docTags.includes(t))
    })
  }
  // 搜索过滤
  if (docSearchQuery.value.trim()) {
    const q = docSearchQuery.value.toLowerCase()
    result = result.filter(d => d.filename.toLowerCase().includes(q))
  }
  return result
})

// ---------- 知识库导出/导入 ----------
const exporting = ref(false)
const importing = ref(false)

async function handleExportKb() {
  if (!kb.currentId) return
  exporting.value = true
  try {
    const data = await api.exportKb(kb.currentId)
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `kb-${kb.current()?.name || 'export'}-${new Date().toISOString().slice(0, 10)}.json`
    a.click()
    URL.revokeObjectURL(url)
    antMessage.success('知识库已导出')
  } catch (e) {
    antMessage.error(`导出失败：${e.message}`)
  } finally {
    exporting.value = false
  }
}

async function handleImportKb() {
  if (!kb.currentId) {
    antMessage.warning('请先选择知识库')
    return
  }
  const input = document.createElement('input')
  input.type = 'file'
  input.accept = '.json'
  input.onchange = async (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    importing.value = true
    try {
      const text = await file.text()
      const data = JSON.parse(text)
      const res = await api.importKb(kb.currentId, data)
      antMessage.success(`已导入 ${res.imported.docs} 个文档、${res.imported.messages} 条消息`)
      await kb.refresh()
      await kb.refreshDocs()
    } catch (err) {
      antMessage.error(`导入失败：${err.message}`)
    } finally {
      importing.value = false
    }
  }
  input.click()
}

const MAX_SIZE = 50 * 1024 * 1024
const ACCEPT = '.pdf,.docx,.pptx,.xlsx,.md,.txt,.doc,.xls,.ppt,.png,.jpg,.jpeg,.bmp,.tiff,.tif'

const docs = computed(() => kb.docs)

onMounted(() => {
  if (!kb.list.length) kb.refresh()
  else if (kb.currentId) kb.refreshDocs()
})

function iconFor(filename) {
  if (!filename.includes('.')) return LinkOutlined
  const ext = filename.slice(filename.lastIndexOf('.')).toLowerCase()
  if (ext === '.pdf') return FilePdfOutlined
  if (ext === '.docx') return FileWordOutlined
  if (ext === '.xlsx') return FileExcelOutlined
  if (ext === '.pptx') return FilePptOutlined
  if (ext === '.md') return FileMarkdownOutlined
  return FileTextOutlined
}

// ---------- 知识库搜索 ----------
const searchQuery = ref('')
const searchResults = ref([])
const searching = ref(false)
const searchOpen = ref(false)

async function handleSearch() {
  if (!searchQuery.value.trim() || !kb.currentId) {
    searchResults.value = []
    return
  }
  searching.value = true
  try {
    const res = await api.searchDocs(kb.currentId, searchQuery.value.trim())
    searchResults.value = res.items || []
    searchOpen.value = true
  } catch (e) {
    antMessage.error(`搜索失败：${e.message}`)
  } finally {
    searching.value = false
  }
}

function highlightText(text, query) {
  if (!query) return text
  const regex = new RegExp(`(${query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi')
  return text.replace(regex, '<mark>$1</mark>')
}

// ---------- 文档预览 ----------
const previewDoc = ref(null)
const previewText = ref('')
const previewLoading = ref(false)
const previewOpen = ref(false)

async function openPreview(doc) {
  if (!kb.currentId) return
  previewDoc.value = doc
  previewOpen.value = true
  previewLoading.value = true
  previewText.value = ''
  try {
    const res = await api.previewDoc(kb.currentId, doc.id)
    previewText.value = res.text || ''
  } catch (e) {
    antMessage.error(`预览失败：${e.message}`)
  } finally {
    previewLoading.value = false
  }
}

function copyPreview() {
  navigator.clipboard.writeText(previewText.value).then(() => {
    antMessage.success('已复制到剪贴板')
  }).catch(() => {
    antMessage.error('复制失败')
  })
}

function downloadPreview() {
  const blob = new Blob([previewText.value], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${previewDoc.value?.filename || '预览'}.txt`
  a.click()
  URL.revokeObjectURL(url)
  antMessage.success('已下载')
}

const pending = ref([])
let pumping = false

async function handleUpload(file) {
  if (!kb.currentId) {
    antMessage.warning('请先创建或选择知识库')
    return false
  }
  if (file.size > MAX_SIZE) {
    antMessage.error(`《${file.name}》超过 50 MB 上限，已跳过`)
    return false
  }
  pending.value.push(file)
  pumpQueue()

// ---------- 批量上传/删除 ----------
const batchMode = ref(false)
const selectedDocIds = ref([])

const allDocsSelected = computed(() => {
  const all = filteredDocs.value
  return all.length > 0 && all.every((d) => selectedDocIds.value.includes(d.id))
})

function toggleSelectDoc(docId) {
  const idx = selectedDocIds.value.indexOf(docId)
  if (idx >= 0) {
    selectedDocIds.value.splice(idx, 1)
  } else {
    selectedDocIds.value.push(docId)
  }
}

function toggleSelectAllDocs() {
  if (allDocsSelected.value) {
    selectedDocIds.value = []
  } else {
    selectedDocIds.value = filteredDocs.value.map((d) => d.id)
  }
}

async function batchDeleteDocs() {
  if (!selectedDocIds.value.length) return
  try {
    for (const docId of selectedDocIds.value) {
      await api.deleteDoc(kb.currentId, docId)
    }
    selectedDocIds.value = []
    batchMode.value = false
    await kb.refreshDocs()
  } catch (e) {
    antMessage.error(`批量删除失败：${e.message}`)
  }
}
  return false
}

async function pumpQueue() {
  if (pumping || !pending.value.length) return
  pumping = true
  uploading.value = true
  progress.value = 0
  let done = 0
  let chunks = 0
  const failed = []
  try {
    while (pending.value.length) {
      const file = pending.value.shift()
      const total = done + pending.value.length + 1
      uploadingName.value = `(${done + 1}/${total}) ${file.name}`
      try {
        const res = await kb.upload(file, (p) => {
          progress.value = Math.round(((done + p / 100) / total) * 100)
        })
        done += 1
        chunks += res.chunk_count
      } catch (e) {
        done += 1
        failed.push(`${file.name}：${e.message}`)
      }
    }
    if (!failed.length) {
      antMessage.success(`批量导入完成：${done} 个文件，共 ${chunks} 个片段`)
    } else if (done - failed.length > 0) {
      antMessage.warning(`成功 ${done - failed.length} 个、失败 ${failed.length} 个：${failed.join('；')}`)
    } else {
      antMessage.error(`全部失败：${failed.join('；')}`)
    }
  } finally {
    pumping = false
    uploading.value = false
    uploadingName.value = ''
  }
}

async function submitFetch() {
  const url = fetchUrl.value.trim()
  if (!url || fetching.value) return
  if (!kb.currentId) {
    antMessage.warning('请先创建或选择知识库')
    return
  }
  fetching.value = true
  try {
    const res = await kb.fetchUrl(url)
    fetchUrl.value = ''
    antMessage.success(`已抓取入库：${res.document.filename}，${res.chunk_count} 个片段`)
  } catch (e) {
    antMessage.error(`抓取失败：${e.message}`)
  } finally {
    fetching.value = false
  }
}

async function submitBatchFetch() {
  const urls = batchUrls.value.split('\n').map(u => u.trim()).filter(Boolean)
  if (!urls.length || batchFetching.value) return
  if (!kb.currentId) {
    antMessage.warning('请先创建或选择知识库')
    return
  }
  batchFetching.value = true
  try {
    const res = await api.batchFetchUrls(kb.currentId, urls)
    if (res.imported > 0) {
      antMessage.success(`成功导入 ${res.imported} 个 URL${res.failed > 0 ? `，失败 ${res.failed} 个` : ''}`)
      await kb.refreshDocs()
    } else {
      antMessage.error(`全部失败：${res.errors.join('；')}`)
    }
    if (res.errors.length > 0 && res.imported > 0) {
      antMessage.warning(`部分失败：${res.errors.join('；')}`)
    }

  } catch (e) {
    antMessage.error(`批量抓取失败：${e.message}`)
  } finally {
    batchFetching.value = false
  }
}

function formatSize(chars) {
  if (chars < 1024) return `${chars} B`
  if (chars < 1024 * 1024) return `${(chars / 1024).toFixed(1)} KB`
  return `${(chars / 1024 / 1024).toFixed(1)} MB`
}

function docStatusLabel(status) {
  const labels = {
    pending: '等待中',
    processing: '索引中...',
    completed: '已索引',
    failed: '失败',
  }
  return labels[status] || '已索引'
}

function docStatusColor(status) {
  const colors = {
    pending: 'default',
    processing: 'processing',
    completed: 'success',
    failed: 'error',
  }
  return colors[status] || 'success'
}

// ---------- 文档对比 ----------
const compareOpen = ref(false)
const compareDocs = ref([])
const compareLoading = ref(false)

async function openCompare(doc) {
  compareOpen.value = true
  compareLoading.value = true
  compareDocs.value = []
  try {
    const res = await api.compareDocs([doc.id])
    compareDocs.value = res.documents || []
  } catch (e) {
    antMessage.error(`对比失败：${e.message}`)
  } finally {
    compareLoading.value = false
  }
}

function confirmDeleteDoc(doc) {
  Modal.confirm({
    title: '删除文档',
    content: `确定删除《${doc.filename}》？其 ${doc.chunk_count} 个片段会一并移除。`,
    okText: '删除',
    okType: 'danger',
    cancelText: '取消',
    async onOk() {
      await kb.removeDoc(doc.id)
      antMessage.success('已删除')
    },
  })
}

function confirmClearDocs(item) {
  Modal.confirm({
    title: '清空文档',
    content: `确定清空「${item.name}」的全部 ${item.doc_count} 个文档？知识库本身保留，对话历史不受影响，且不可恢复。`,
    okText: '清空',
    okType: 'danger',
    cancelText: '取消',
    async onOk() {
      const res = await kb.clearDocs()
      antMessage.success(`已清空 ${res.docs} 个文档`)
    },
  })
}

function confirmDeleteKb(item) {
  Modal.confirm({
    title: '删除知识库',
    content: `确定删除「${item.name}」？其中 ${item.doc_count} 个文档将全部移除，且不可恢复。`,
    okText: '删除',
    okType: 'danger',
    cancelText: '取消',
    async onOk() {
      await kb.remove(item.id)
      antMessage.success('已删除')
    },
  })
}

async function submitCreate() {
  const name = newName.value.trim()
  if (!name) return
  try {
    await kb.create(name)
    creating.value = false
    newName.value = ''
    antMessage.success('知识库已创建')
  } catch (e) {
    antMessage.error(e.message)
  }
}

function formatTime(s) {
  return (s || '').replace('T', ' ').slice(0, 16)
}
</script>

<template>
  <div class="knowledge">
    <!-- ---------- 左：知识库列表 ---------- -->
    <aside class="kb-col">
      <div class="col-head">
        <span class="col-title">知识库</span>
        <a-button type="text" size="small" @click="creating = true">
          <template #icon><PlusOutlined /></template>
        </a-button>
      </div>

      <div class="kb-list">
        <div
          v-for="item in kb.list"
          :key="item.id"
          class="kb-card"
          :class="{ active: item.id === kb.currentId }"
          @click="kb.select(item.id)"
        >
          <div class="kb-name">{{ item.name }}</div>
          <div class="kb-meta muted">
            {{ item.doc_count }} 文档 · {{ item.chunk_count }} 片段
          </div>
          <div class="kb-actions">
            <button class="kb-action" title="导出知识库" @click.stop="handleExportKb">
              <DownloadOutlined />
            </button>
            <button class="kb-action" title="导入到当前库" @click.stop="handleImportKb">
              <UploadOutlined />
            </button>
            <button class="kb-del" title="删除知识库" @click.stop="confirmDeleteKb(item)">
              <DeleteOutlined />
            </button>
          </div>
        </div>

        <div v-if="!kb.list.length" class="kb-empty muted">
          还没有知识库
        </div>
      </div>

        <!-- 知识库统计 -->
        <div v-if="kb.currentId" class="kb-stats">
          <div class="kb-stats-title">知识库统计</div>
          <div class="kb-stats-grid">
            <div class="kb-stat-item">
              <div class="kb-stat-value">{{ kb.current()?.doc_count || 0 }}</div>
              <div class="kb-stat-label">文档数</div>
            </div>
            <div class="kb-stat-item">
              <div class="kb-stat-value">{{ kb.current()?.chunk_count || 0 }}</div>
              <div class="kb-stat-label">片段数</div>
            </div>
            <div class="kb-stat-item">
              <div class="kb-stat-value">{{ formatSize(kb.current()?.total_chars || 0) }}</div>
              <div class="kb-stat-label">存储占用</div>
            </div>
            <div class="kb-stat-item">
              <div class="kb-stat-value">{{ kb.current()?.session_count || 0 }}</div>
              <div class="kb-stat-label">会话数</div>
            </div>
          </div>
        </div>
    </aside>

    <!-- ---------- 右：文档管理 ---------- -->
    <section class="doc-col">
      <template v-if="kb.currentId">
        <div class="col-head main">
          <span class="col-title">{{ kb.current()?.name }}</span>
          <div class="head-actions">
            <a-button
              size="small"
              type="text"
              danger
              :disabled="!docs.length"
              @click="confirmClearDocs(kb.current())"
            >
              清空文档
            </a-button>
            <a-button
              size="small"
              :disabled="!docs.length"
              @click="router.push('/chat')"
            >
              <template #icon><MessageOutlined /></template>
              去提问
            </a-button>
          </div>
        </div>

        <div class="doc-body">

          <!-- 知识库搜索 -->
          <div class="search-row">
            <a-input
              v-model:value="searchQuery"
              placeholder="搜索文档内容…"
              :disabled="searching"
              @pressEnter="handleSearch"
            >
              <template #prefix><SearchOutlined /></template>
            </a-input>
            <a-button type="primary" :loading="searching" @click="handleSearch">
              搜索
            </a-button>
          </div>

          <!-- 搜索结果 -->
          <div v-if="searchOpen && searchResults.length" class="search-results">
            <div class="search-result-item" v-for="r in searchResults" :key="r.id">
              <div class="search-result-file">{{ r.filename }}</div>
              <div class="search-result-text" v-html="highlightText(r.text, searchQuery)"></div>
            </div>
          </div>

          <div v-if="searchOpen && !searchResults.length && !searching" class="search-empty muted">
            未找到匹配内容
          </div>

          <!-- 文档列表 -->
          <a-upload-dragger
            :accept="ACCEPT"
            multiple
            :show-upload-list="false"
            :before-upload="handleUpload"
            :disabled="uploading"
            class="dragger"
          >
            <p class="ant-upload-drag-icon"><InboxOutlined /></p>
            <p class="ant-upload-text">点击或拖拽文件到此处导入（可多选）</p>
            <p class="ant-upload-hint">
              支持 PDF / Word / PPT / Excel / Markdown / 纯文本，批量依次导入，单个文件不超过 50 MB
            </p>
          </a-upload-dragger>

          <!-- URL 抓取 -->
          <div class="url-row">
            <a-input
              v-model:value="fetchUrl"
              placeholder="粘贴文章链接，抓取正文入库（仅 http/https）"
              :disabled="uploading || fetching"
              @pressEnter="submitFetch"
            />
            <a-button
              type="primary"
              :loading="fetching"
              :disabled="!fetchUrl.trim() || uploading"
              @click="submitFetch"
            >
              <template #icon><LinkOutlined /></template>
              抓取
            </a-button>
          </div>

          <!-- 批量 URL 导入 -->
          <div class="batch-url-section">
            <div class="batch-url-header">
              <span class="batch-url-title">批量 URL 导入</span>
              <a-button size="small" type="link" @click="showBatchUrl = !showBatchUrl">
                {{ showBatchUrl ? '收起' : '展开' }}
              </a-button>
            </div>
            <div v-if="showBatchUrl" class="batch-url-body">
              <a-textarea
                v-model:value="batchUrls"
                placeholder="每行一个 URL，最多 50 个"
                :rows="4"
                :disabled="batchFetching"
              />
              <div class="batch-url-actions">
                <a-button
                  type="primary"
                  size="small"
                  :loading="batchFetching"
                  :disabled="!batchUrls.trim()"
                  @click="submitBatchFetch"
                >
                  批量抓取
                </a-button>
                <span class="muted">已输入 {{ batchUrls.split('\n').filter(u => u.trim()).length }} 个 URL</span>
              </div>
            </div>
          </div>

          <!-- 爬取配置 -->
          <div class="fetch-config-section">
            <div class="fetch-config-header">
              <span class="fetch-config-title">爬取配置</span>
              <a-button size="small" type="link" @click="showFetchConfig = !showFetchConfig">
                {{ showFetchConfig ? '收起' : '展开' }}
              </a-button>
            </div>
            <div v-if="showFetchConfig" class="fetch-config-body">
              <div class="fetch-config-item">
                <label class="fetch-config-label">起始 URL</label>
                <a-input
                  v-model:value="fetchConfigUrl"
                  placeholder="https://example.com"
                  :disabled="recursiveFetching"
                />
              </div>
              <div class="fetch-config-item">
                <label class="fetch-config-label">爬取深度：{{ fetchConfigDepth }}</label>
                <a-slider v-model:value="fetchConfigDepth" :min="1" :max="5" :step="1" />
              </div>
              <div class="fetch-config-item">
                <label class="fetch-config-label">最大页面数：{{ fetchConfigMaxPages }}</label>
                <a-slider v-model:value="fetchConfigMaxPages" :min="10" :max="200" :step="10" />
              </div>
              <div class="fetch-config-item">
                <label class="fetch-config-label">排除路径（每行一个）</label>
                <a-textarea
                  v-model:value="fetchConfigExclude"
                  placeholder="/admin&#10;/login&#10;/api"
                  :rows="3"
                  :disabled="recursiveFetching"
                />
              </div>
              <div class="fetch-config-actions">
                <a-button
                  type="primary"
                  size="small"
                  :loading="recursiveFetching"
                  :disabled="!fetchConfigUrl.trim()"
                  @click="submitRecursiveFetch"
                >
                  开始爬取
                </a-button>
              </div>
            </div>
          </div>

          <!-- 定时爬取 -->
          <div class="schedule-section">
            <div class="schedule-header">
              <span class="schedule-title">定时爬取</span>
              <a-button size="small" type="link" @click="showSchedule = !showSchedule">
                {{ showSchedule ? '收起' : '展开' }}
              </a-button>
            </div>
            <div v-if="showSchedule" class="schedule-body">
              <div class="schedule-item">
                <label class="schedule-label">URL</label>
                <a-input
                  v-model:value="scheduleUrl"
                  placeholder="https://example.com"
                  :disabled="scheduleLoading"
                />
              </div>
              <div class="schedule-item">
                <label class="schedule-label">频率</label>
                <a-select
                  v-model:value="scheduleFrequency"
                  :options="[
                    { value: 'hourly', label: '每小时' },
                    { value: 'daily', label: '每天' },
                    { value: 'weekly', label: '每周' },
                  ]"
                  :disabled="scheduleLoading"
                />
              </div>
              <div class="schedule-actions">
                <a-button
                  type="primary"
                  size="small"
                  :loading="scheduleLoading"
                  :disabled="!scheduleUrl.trim()"
                  @click="submitSchedule"
                >
                  创建任务
                </a-button>
              </div>
              <div v-if="schedules.length" class="schedule-list">
                <div v-for="s in schedules" :key="s.id" class="schedule-item-row">
                  <span class="schedule-url">{{ s.url }}</span>
                  <span class="schedule-freq">{{ s.frequency }}</span>
                  <a-button size="small" type="text" @click="deleteSchedule(s.id)">删除</a-button>
                </div>
              </div>
            </div>
          </div>

          <!-- 增量爬取 -->
          <div class="incremental-section">
            <div class="incremental-header">
              <span class="incremental-title">增量爬取</span>
              <a-button size="small" type="link" @click="showIncremental = !showIncremental">
                {{ showIncremental ? '收起' : '展开' }}
              </a-button>
            </div>
            <div v-if="showIncremental" class="incremental-body">
              <div class="incremental-item">
                <label class="incremental-label">URL</label>
                <a-input
                  v-model:value="incrementalUrl"
                  placeholder="https://example.com"
                  :disabled="incrementalFetching"
                />
              </div>
              <div class="incremental-actions">
                <a-button
                  type="primary"
                  size="small"
                  :loading="incrementalFetching"
                  :disabled="!incrementalUrl.trim()"
                  @click="submitIncrementalFetch"
                >
                  开始增量爬取
                </a-button>
              </div>
            </div>
          </div>

          <!-- Agent 任务面板 -->
          <div class="agent-task-section">
            <div class="agent-task-header">
              <span class="agent-task-title">Agent 任务</span>
              <a-button size="small" type="link" @click="showAgentTask = !showAgentTask">
                {{ showAgentTask ? '收起' : '展开' }}
              </a-button>
            </div>
            <div v-if="showAgentTask" class="agent-task-body">
              <div class="agent-task-item">
                <label class="agent-task-label">任务标题</label>
                <a-input
                  v-model:value="agentTaskTitle"
                  placeholder="例如：分析文档内容"
                  :disabled="agentTaskLoading"
                />
              </div>
              <div class="agent-task-item">
                <label class="agent-task-label">任务描述</label>
                <a-textarea
                  v-model:value="agentTaskDesc"
                  placeholder="描述任务目标"
                  :rows="2"
                  :disabled="agentTaskLoading"
                />
              </div>
              <div class="agent-task-actions">
                <a-button
                  type="primary"
                  size="small"
                  :loading="agentTaskLoading"
                  :disabled="!agentTaskTitle.trim()"
                  @click="submitAgentTask"
                >
                  创建任务
                </a-button>
              </div>
              <div v-if="agentTasks.length" class="agent-task-list">
                <div v-for="t in agentTasks" :key="t.id" class="agent-task-item-row">
                  <span class="agent-task-name">{{ t.title }}</span>
                  <a-tag :color="t.status === 'completed' ? 'success' : t.status === 'failed' ? 'error' : 'processing'">
                    {{ t.status }}
                  </a-tag>
                  <a-button size="small" type="text" @click="executeTask(t.id)" :disabled="t.status === 'running'">
                    执行
                  </a-button>
                  <a-button size="small" type="text" @click="deleteTask(t.id)">删除</a-button>
                </div>
              </div>
            </div>
          </div>

          <div v-if="uploading" class="progress">
            <span class="progress-name">{{ uploadingName }}</span>
            <a-progress :percent="progress" size="small" :status="progress < 100 ? 'active' : 'success'" />
            <span class="muted">解析并建立索引中…</span>
          </div>

          <!-- 文档搜索 -->
          <div class="doc-search">
            <a-input
              v-model:value="docSearchQuery"
              size="small"
              placeholder="搜索文档..."
              allow-clear
            />
          </div>

          <!-- 批量操作 -->
          <div v-if="batchMode" class="batch-actions">
            <a-button size="small" @click="toggleSelectAllDocs">
              {{ allDocsSelected ? '取消全选' : '全选' }}
            </a-button>
            <a-button size="small" danger :disabled="selectedDocIds.length === 0" @click="batchDeleteDocs">
              删除 ({{ selectedDocIds.length }})
            </a-button>
            <a-button size="small" @click="batchMode = false">取消</a-button>
          </div>

          <!-- 标签筛选 -->
          <div v-if="allTags.length" class="tag-filter">
            <span class="tag-filter-label">标签筛选：</span>
            <a-tag
              v-for="tag in allTags"
              :key="tag"
              :color="selectedTags.includes(tag) ? 'blue' : ''"
              class="tag-filter-item"
              @click="toggleTagFilter(tag)"
            >
              {{ tag }}
            </a-tag>
            <a-button size="small" type="text" @click="selectedTags = []">清除</a-button>
          </div>

          <!-- 加载骨架屏 -->
          <div v-if="kb.loading && !docs.length" class="docs">
            <div v-for="i in 3" :key="i" class="doc-card">
              <a-skeleton avatar :paragraph="{ rows: 1 }" active />
            </div>
          </div>

          <!-- 文档列表 -->
          <div v-else-if="filteredDocs.length" class="docs">
            <div v-for="doc in filteredDocs" :key="doc.id" class="doc-card">
              <a-checkbox
                v-if="batchMode"
                :checked="selectedDocIds.includes(doc.id)"
                @change="toggleSelectDoc(doc.id)"
              />
              <component :is="iconFor(doc.filename)" class="doc-icon" />
              <div class="doc-info">
                <div class="doc-name" :title="doc.filename">{{ doc.filename }}</div>
                <div class="doc-meta muted">
                  {{ doc.chunk_count }} 个片段 · {{ formatTime(doc.created_at) }}
                </div>
              </div>
              <a-tag :color="docStatusColor(doc.status)">{{ docStatusLabel(doc.status) }}</a-tag>
              <button class="doc-action" title="对比文档" @click="openCompare(doc)">
                <FileTextOutlined />
              </button>
              <button class="doc-del" title="删除文档" @click="confirmDeleteDoc(doc)">
                <DeleteOutlined />
              </button>
            </div>
          </div>

          <div v-else-if="!uploading" class="doc-empty">
            <div class="empty-icon"><InboxOutlined /></div>
            <p class="muted">这个知识库还没有文档，从上方导入一份资料开始。</p>
          </div>

        </div>
      </template>

      <!-- 未选知识库 -->
      <div v-else class="doc-empty full">
        <div class="empty-icon"><InboxOutlined /></div>
        <p class="muted">先在左侧新建一个知识库，再导入文档。</p>
        <a-button type="primary" @click="creating = true">
          <template #icon><PlusOutlined /></template>
          新建知识库
        </a-button>
      </div>
    </section>

    <!-- ---------- 新建弹窗 ---------- -->
    <a-modal
      v-model:open="creating"
      title="新建知识库"
      ok-text="创建"
      cancel-text="取消"
      :ok-button-props="{ disabled: !newName.trim() }"
      @ok="submitCreate"
    >
      <a-input
        v-model:value="newName"
        placeholder="例如：产品手册、售后政策"
        :maxlength="64"
        show-count
        @press-enter="submitCreate"
      />
    </a-modal>

    <!-- ---------- 文档预览弹窗 ---------- -->
    <a-modal
      v-model:open="previewOpen"
      :title="previewDoc?.filename || '文档预览'"
      :footer="null"
      width="800px"
    >
      <div v-if="previewLoading" class="preview-loading">
        <a-spin />
      </div>
      <div v-else class="preview-body">
        <div class="preview-toolbar">
          <a-button size="small" @click="copyPreview">
            <template #icon><FileTextOutlined /></template>
            复制
          </a-button>
          <a-button size="small" @click="downloadPreview">
            <template #icon><DownloadOutlined /></template>
            下载
          </a-button>
          <span class="preview-stats muted">
            {{ previewText.length }} 字符 · {{ previewDoc?.chunk_count || 0 }} 片段
          </span>
        </div>
        <pre>{{ previewText }}</pre>
      </div>
    </a-modal>

    <!-- ---------- 文档对比弹窗 ---------- -->
    <a-modal
      v-model:open="compareOpen"
      title="文档对比"
      :footer="null"
      width="900px"
    >
      <div v-if="compareLoading" class="compare-loading">
        <a-spin />
      </div>
      <div v-else class="compare-body">
        <div v-for="doc in compareDocs" :key="doc.id" class="compare-doc">
          <div class="compare-doc-header">
            <span class="compare-doc-name">{{ doc.filename }}</span>
            <span class="compare-doc-meta muted">{{ doc.chunk_count }} 个片段</span>
          </div>
          <pre class="compare-doc-content">{{ doc.content }}</pre>
        </div>
      </div>
    </a-modal>
  </div>
</template>

<style scoped>
.knowledge {
  display: flex;
  height: 100%;
  overflow: hidden;
}

/* ---------- 左列 ---------- */
.kb-col {
  width: 268px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--border);
  background: var(--bg-sider);
}
.col-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
}
.col-head.main {
  justify-content: space-between;
  background: var(--bg-panel);
}
.col-title {
  font-size: 14px;
  font-weight: 600;
}
.head-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}

.kb-list {
  flex: 1;
  overflow-y: auto;
  padding: 10px;
}
.kb-card {
  position: relative;
  padding: 10px 12px;
  margin-bottom: 6px;
  border: 1px solid transparent;
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.15s;
}
.kb-card:hover {
  background: var(--bg-hover);
}
.kb-card.active {
  background: var(--accent-soft);
  border-color: var(--accent);
  box-shadow: 0 2px 8px rgba(249, 115, 22, 0.12);
}
.kb-name {
  font-size: 13.5px;
  font-weight: 600;
  margin-bottom: 3px;
  padding-right: 22px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.kb-card.active .kb-name {
  color: var(--accent);
}
.kb-meta {
  font-size: 11.5px;
}
.kb-del {
  position: absolute;
  top: 9px;
  right: 8px;
  width: 22px;
  height: 22px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: var(--text-3);
  font-size: 12px;
  cursor: pointer;
  opacity: 0;
  transition: all 0.15s;
}
.kb-card:hover .kb-del {
  opacity: 1;
}
.kb-del:hover {
  background: rgba(245, 63, 63, 0.12);
  color: #f53f3f;
}
.kb-empty {
  padding: 24px 8px;
  text-align: center;
  font-size: 12.5px;
}

/* ---------- 右列 ---------- */
.doc-col {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  background: var(--bg-app);
}
.doc-body {
  flex: 1;
  overflow-y: auto;
  padding: 18px 22px;
}

.dragger :deep(.ant-upload-drag) {
  height: auto;
  background: var(--bg-panel);
  border-radius: 12px;
  border: 1px dashed var(--border-strong);
}
.dragger :deep(.ant-upload-btn) {
  padding: 22px 0;
}
.dragger :deep(.ant-upload-drag-icon) {
  margin-bottom: 10px;
}
.dragger :deep(.ant-upload-drag-icon .anticon) {
  color: var(--accent);
}
.dragger :deep(.ant-upload-text) {
  color: var(--text-1);
  font-size: 14px;
}
.dragger :deep(.ant-upload-hint) {
  color: var(--text-3);
  font-size: 12.5px;
}

.progress {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 14px;
  padding: 10px 14px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--bg-panel);
  font-size: 12.5px;
}
.url-row {
  display: flex;
  gap: 10px;
  margin-top: 14px;
}
.progress :deep(.ant-progress) {
  flex: 1;
  margin: 0;
}
.progress-name {
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 600;
}

/* ---------- 文档卡片 ---------- */
.docs {
  margin-top: 18px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.doc-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 11px 14px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--bg-panel);
  transition: box-shadow 0.15s, border-color 0.15s;
}
.doc-card:hover {
  border-color: var(--border-strong);
  box-shadow: var(--shadow-sm);
}
.doc-icon {
  font-size: 19px;
  color: var(--accent);
  flex-shrink: 0;
}
.doc-info {
  flex: 1;
  min-width: 0;
}
.doc-name {
  font-size: 13.5px;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.doc-meta {
  font-size: 11.5px;
  margin-top: 2px;
}
.doc-del {
  width: 26px;
  height: 26px;
  flex-shrink: 0;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: var(--text-3);
  cursor: pointer;
  transition: all 0.15s;
}
.doc-del:hover {
  background: rgba(245, 63, 63, 0.12);
  color: #f53f3f;
}

/* ---------- 空状态 ---------- */
.doc-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 48px 20px;
  text-align: center;
}
.doc-empty.full {
  height: 100%;
}
.empty-icon {
  width: 48px;
  height: 48px;
  border-radius: 14px;
  background: var(--bg-hover);
  color: var(--text-3);
  font-size: 21px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.doc-empty p {
  margin: 0;
  font-size: 13px;
  max-width: 380px;
  line-height: 1.7;
}
.graph-card {
  margin-top: 14px;
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 12px 14px;
  background: var(--bg-panel);
}
.graph-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.graph-nodes {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 8px;
}
.graph-edges {
  font-size: 11.5px;
  color: var(--text-3);
  line-height: 1.8;
}

/* ---------- 知识库搜索 ---------- */
.search-row {
  display: flex;
  gap: 10px;
  margin-bottom: 14px;
}
.search-results {
  margin-bottom: 14px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--bg-panel);
  overflow: hidden;
}
.search-result-item {
  padding: 10px 14px;
  border-bottom: 1px solid var(--border);
}
.search-result-item:last-child {
  border-bottom: none;
}
.search-result-file {
  font-size: 12px;
  font-weight: 600;
  color: var(--accent);
  margin-bottom: 4px;
}
.search-result-text {
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--text-2);
}
.search-result-text :deep(mark) {
  background: rgba(249, 115, 22, 0.2);
  color: var(--accent);
  padding: 0 2px;
  border-radius: 3px;
}
.search-empty {
  padding: 16px;
  text-align: center;
  font-size: 12.5px;
}

/* ---------- 文档预览 ---------- */
.preview-loading {
  display: flex;
  justify-content: center;
  padding: 40px 0;
}
.preview-body {
  max-height: 500px;
  overflow-y: auto;
}
.preview-body pre {
  margin: 0;
  padding: 14px;
  border-radius: 8px;
  background: var(--bg-code);
  font-size: 12.5px;

/* ---------- 知识图谱 ---------- */
.graph-section {
  margin-bottom: 12px;
}
.graph-section:last-child {
  margin-bottom: 0;
}
.graph-section-title {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-3);
  margin-bottom: 6px;
  text-transform: uppercase;
  letter-spacing: 0.3px;
}
.graph-node {
  margin: 2px;
}
.graph-edges {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.graph-edge {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  padding: 4px 8px;
  border-radius: 6px;
  background: var(--bg-code);
}
.edge-node {
  font-weight: 500;
  color: var(--text-1);
}
.edge-line {
  color: var(--text-3);
}
.edge-weight {
  color: var(--text-3);
  font-size: 11px;
}
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--text-1);
}
</style>
