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
    await refresh()
    await refreshDocs()
  }

  async function upload(file, onProgress) {
    const res = await api.uploadDoc(currentId.value, file, onProgress)
    await refresh()
    await refreshDocs()
    return res
  }

  return {
    list, currentId, docs, loading, current,
    refresh, select, refreshDocs, create, remove, removeDoc, upload,
  }
})
