'use strict'

/**
 * 预加载脚本
 *
 * 渲染进程开了 contextIsolation + sandbox，无法直接访问 Node，
 * 这里只暴露必要的三件事：查后端地址、订阅后端状态、用系统浏览器开外链。
 */

const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('ragBridge', {
  /** 查询后端当前状态：{ status: 'starting'|'ready'|'error', url, message } */
  getBackendInfo: () => ipcRenderer.invoke('backend:info'),

  /**
   * 订阅后端状态变化，返回取消订阅的函数。
   * 只把数据透传给回调，不把 IpcRendererEvent 暴露出去。
   */
  onBackendStatus: (callback) => {
    const handler = (_event, info) => callback(info)
    ipcRenderer.on('backend:status', handler)
    return () => ipcRenderer.off('backend:status', handler)
  },

  openExternal: (url) => ipcRenderer.invoke('shell:open', url),
})
