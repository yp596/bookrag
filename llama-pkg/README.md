# llama 随包暂存区（打包时才用，平时为空）

桌面端启动时若在包内 `resources/llama/` 找到推理服务会自动拉起，
找不到则静默跳过（见 `electron/main.js` 的 `startLlamaIfBundled`）。

**打包前**把下面两样拷进来（体积大，勿提交）：

```
llama-pkg/
├── llama-server.exe
└── models/
    └── MiniCPM5-1B-F16.gguf
```

本机来源：`D:\llmma\llama-b10853-bin-win-cuda-12.4-x64`（exe），
模型文件另行下载。空目录不影响 `npm run pack`。
