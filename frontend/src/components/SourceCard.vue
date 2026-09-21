<script setup>
import { ref } from 'vue'
import { FileTextOutlined, DownOutlined, RightOutlined } from '@ant-design/icons-vue'

const props = defineProps({
  sources: { type: Array, default: () => [] },
})

const expanded = ref(new Set())

function toggle(i) {
  const next = new Set(expanded.value)
  next.has(i) ? next.delete(i) : next.add(i)
  expanded.value = next
}

/** 相关度归一化成 0-100 的直观百分比 */
function relevance(score) {
  return Math.min(100, Math.round((score / 4) * 100))
}
</script>

<template>
  <div v-if="sources.length" class="sources">
    <div class="head">
      <FileTextOutlined />
      <span>引用来源</span>
      <span class="count">{{ sources.length }}</span>
    </div>

    <div
      v-for="(s, i) in sources"
      :key="i"
      class="item"
      :class="{ open: expanded.has(i) }"
    >
      <div class="item-head" @click="toggle(i)">
        <component :is="expanded.has(i) ? DownOutlined : RightOutlined" class="caret" />
        <span class="label">{{ s.section || s.title || '片段' }}</span>
        <span v-if="s.source" class="file">{{ s.source }}</span>
        <span class="score" :style="{ '--pct': relevance(s.score) + '%' }">
          <span class="bar" />
          相关度 {{ relevance(s.score) }}%
        </span>
      </div>
      <div v-show="expanded.has(i)" class="item-body">{{ s.text }}</div>
    </div>
  </div>
</template>

<style scoped>
.sources {
  margin-top: 12px;
  border: 1px solid var(--border);
  border-radius: 9px;
  overflow: hidden;
  background: var(--bg-panel);
}

.head {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 8px 12px;
  background: var(--bg-code);
  border-bottom: 1px solid var(--border);
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text-2);
}
.count {
  padding: 0 6px;
  border-radius: 8px;
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 11px;
}

.item + .item {
  border-top: 1px solid var(--border);
}
.item.open {
  background: var(--bg-code);
}

.item-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  cursor: pointer;
  font-size: 12.5px;
  transition: background 0.15s;
}
.item-head:hover {
  background: var(--bg-hover);
}
.caret {
  font-size: 10px;
  color: var(--text-3);
  flex-shrink: 0;
}
.label {
  font-weight: 600;
  color: var(--text-1);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.file {
  color: var(--text-3);
  font-size: 11.5px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 220px;
}

/* 相关度用小进度条表示，比裸数字更好读 */
.score {
  position: relative;
  margin-left: auto;
  flex-shrink: 0;
  padding: 2px 8px 2px 9px;
  border-radius: 9px;
  background: var(--bg-hover);
  color: var(--text-3);
  font-size: 11px;
  overflow: hidden;
  white-space: nowrap;
}
.bar {
  position: absolute;
  inset: 0 auto 0 0;
  width: var(--pct);
  background: var(--accent-soft);
}

.item-body {
  padding: 4px 14px 12px 30px;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--text-2);
  white-space: pre-wrap;
  word-break: break-word;
  border-top: 1px dashed var(--border);
}
</style>
