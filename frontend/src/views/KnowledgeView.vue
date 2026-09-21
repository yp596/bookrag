<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Modal, message as antMessage } from 'ant-design-vue'
import {
  InboxOutlined,
  FileTextOutlined,
  FilePdfOutlined,
  FileWordOutlined,
  FileMarkdownOutlined,
  DeleteOutlined,
  PlusOutlined,
  MessageOutlined,
} from '@ant-design/icons-vue'
import { useKbStore } from '../stores/kb'

const kb = useKbStore()
const router = useRouter()

const uploading = ref(false)
const progress = ref(0)
const uploadingName = ref('')
const creating = ref(false)
const newName = ref('')

const MAX_SIZE = 50 * 1024 * 1024
const ACCEPT = '.pdf,.docx,.md,.txt'

const docs = computed(() => kb.docs)

onMounted(() => {
  if (!kb.list.length) kb.refresh()
  else if (kb.currentId) kb.refreshDocs()
})

function iconFor(filename) {
  const ext = filename.slice(filename.lastIndexOf('.')).toLowerCase()
  if (ext === '.pdf') return FilePdfOutlined
  if (ext === '.docx') return FileWordOutlined
  if (ext === '.md') return FileMarkdownOutlined
  return FileTextOutlined
}

async function handleUpload(file) {
  if (!kb.currentId) {
    antMessage.warning('请先创建或选择知识库')
    return false
  }
  if (file.size > MAX_SIZE) {
    antMessage.error('文件超过 50 MB 上限')
    return false
  }

  uploading.value = true
  progress.value = 0
  uploadingName.value = file.name
  try {
    const res = await kb.upload(file, (p) => (progress.value = p))
    antMessage.success(`《${file.name}》导入完成，生成 ${res.chunk_count} 个片段`)
  } catch (e) {
    antMessage.error(e.message)
  } finally {
    uploading.value = false
    uploadingName.value = ''
  }
  // 返回 false 阻止 antd 自身上传，实际请求已由 store 发出
  return false
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
          <button class="kb-del" title="删除知识库" @click.stop="confirmDeleteKb(item)">
            <DeleteOutlined />
          </button>
        </div>

        <div v-if="!kb.list.length" class="kb-empty muted">
          还没有知识库
        </div>
      </div>
    </aside>

    <!-- ---------- 右：文档管理 ---------- -->
    <section class="doc-col">
      <template v-if="kb.currentId">
        <div class="col-head main">
          <span class="col-title">{{ kb.current()?.name }}</span>
          <a-button
            size="small"
            :disabled="!docs.length"
            @click="router.push('/chat')"
          >
            <template #icon><MessageOutlined /></template>
            去提问
          </a-button>
        </div>

        <div class="doc-body">
          <a-upload-dragger
            :accept="ACCEPT"
            :show-upload-list="false"
            :before-upload="handleUpload"
            :disabled="uploading"
            class="dragger"
          >
            <p class="ant-upload-drag-icon"><InboxOutlined /></p>
            <p class="ant-upload-text">点击或拖拽文件到此处导入</p>
            <p class="ant-upload-hint">
              支持 PDF / Word(docx) / Markdown / 纯文本，单个文件不超过 50 MB
            </p>
          </a-upload-dragger>

          <div v-if="uploading" class="progress">
            <span class="progress-name">{{ uploadingName }}</span>
            <a-progress :percent="progress" size="small" :status="progress < 100 ? 'active' : 'success'" />
            <span class="muted">解析并建立索引中…</span>
          </div>

          <!-- 文档列表 -->
          <div v-if="docs.length" class="docs">
            <div v-for="doc in docs" :key="doc.id" class="doc-card">
              <component :is="iconFor(doc.filename)" class="doc-icon" />
              <div class="doc-info">
                <div class="doc-name" :title="doc.filename">{{ doc.filename }}</div>
                <div class="doc-meta muted">
                  {{ doc.chunk_count }} 个片段 · {{ formatTime(doc.created_at) }}
                </div>
              </div>
              <a-tag color="success">已索引</a-tag>
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
  border-radius: 9px;
  cursor: pointer;
  transition: all 0.15s;
}
.kb-card:hover {
  background: var(--bg-hover);
}
.kb-card.active {
  background: var(--accent-soft);
  border-color: var(--accent);
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
  border-radius: 6px;
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
  /* antd 默认 height:100%，会把拖拽区撑满整列、把文档列表挤出视口 */
  height: auto;
  background: var(--bg-panel);
  border-radius: 11px;
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
  border-radius: 9px;
  background: var(--bg-panel);
  font-size: 12.5px;
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
  border-radius: 9px;
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
  border-radius: 7px;
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
  border-radius: 13px;
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
</style>
