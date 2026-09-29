import { ref } from 'vue'
import { message as antMessage } from 'ant-design-vue'

/** 复制到剪贴板 composable，带成功状态反馈 */
export function useClipboard(timeout = 1500) {
  const copied = ref(false)
  let timer = null

  async function copy(text) {
    try {
      await navigator.clipboard.writeText(text)
      copied.value = true
      clearTimeout(timer)
      timer = setTimeout(() => { copied.value = false }, timeout)
    } catch {
      antMessage.error('复制失败')
    }
  }

  return { copied, copy }
}
