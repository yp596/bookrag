import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '../api/client'

const CURRENT_KEY = 'rag-current-kb'

export const useKbStore = defineStore('kb', () => {
  const list = ref([])
  const currentId = ref(localStorage.getItem(CURRENT_KEY) || '')
  const docs = ref([])
  const loading = ref(false)

  const current = () => list.value.find((k) => k.id === currentId.value) || null

  async function refresh() {
    loading.value = true
    try {
      const { items } = await api.listKbs()
      list.value = items
      // 当前库被删除后自动回落到第一个
      if (!list.value.some((k) => k.id === currentId.value)) {
        select(list.value[0]?.id || '')
      }
    } finally {
      loading.value = false
    }
  }

  /** 并行刷新知识库列表 + 文档列表（替代 refresh() + refreshDocs() 两次串行请求） */
  async function refreshAll() {
    loading.value = true
    try {
      const [{ items }, { items: docItems }] = await Promise.all([
        api.listKbs(),
        currentId.value ? api.listDocs(currentId.value) : Promise.resolve({ items: [] }),
      ])
      list.value = items
      docs.value = docItems
      if (!list.value.some((k) => k.id === currentId.value)) {
        select(list.value[0]?.id || '')
      }
    } finally {
      loading.value = false
    }
  }

  function select(kbId) {
    currentId.value = kbId
    localStorage.setItem(CURRENT_KEY, kbId)
    docs.value = []
    if (kbId) refreshDocs(kbId)
  }

  async function refreshDocs(kbId = currentId.value) {
    if (!kbId) {
      docs.value = []
      return
    }
    const { items } = await api.listDocs(kbId)
    docs.value = items
  }

  async function create(name) {
    const kb = await api.createKb(name)
    await refresh()
    select(kb.id)
    return kb
  }

  async function remove(kbId) {
    await api.deleteKb(kbId)
    await refresh()
  }

  async function removeDoc(docId) {
    await api.deleteDoc(currentId.value, docId)
    await refreshAll()
  }

  async function clearDocs() {
    const res = await api.clearDocs(currentId.value)
    await refreshAll()
    return res
  }

  async function upload(file, onProgress) {
    const res = await api.uploadDoc(currentId.value, file, onProgress)
    await refreshAll()
    return res
  }

  /** 抓取网页正文入库（与 upload 同样的刷新语义） */
  async function fetchUrl(url) {
    const res = await api.fetchUrl(currentId.value, url)
    await refreshAll()
    return res
  }

  return {
    list, currentId, docs, loading, current,
    refresh, refreshAll, select, refreshDocs, create, remove, removeDoc, clearDocs, upload, fetchUrl,
  }
})
