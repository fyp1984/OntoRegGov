# evidence-kit · 合规自查取证工具包

供 OpenClaw 智能体在合规自查中**自主调用**的取证工具（智能体经 exec 执行）。
平台不再预处理证据内容——挑文件、读文件、转写音频、识别图片、语义判定，
全部由智能体自主完成；本工具包只提供"逐字抽取"的确定性能力。

## read_evidence.py

```
<kit>\.venv\Scripts\python.exe <kit>\read_evidence.py <文件绝对路径> [--max-chars N]
```

- 支持：txt/md/csv/json/xml/html、docx/xlsx/pptx/pdf/rtf/eml/zip、odt/ods/odp/vsdx、
  mp3/wav/m4a/flac/ogg/aac（本地 faster-whisper 逐字转写，带时间戳，零加工）
- 图片（png/jpg 等）：**不用本工具**——智能体的 read 工具可直接视觉识别
- 输出逐字文本到 stdout；失败输出 `ERROR: 原因`（退出码非 0）
- 依赖：python-docx / openpyxl / python-pptx / pypdf / faster-whisper / numpy
- whisper 模型：本机 HF 缓存（Systran/faster-whisper-small），离线加载（HF_HUB_OFFLINE=1）
- 音频解码：自动探测 ffmpeg（环境变量 FFMPEG 可显式指定）

## 环境重建（依赖损坏时）

```
python -m venv .venv
.venv\Scripts\pip install faster-whisper python-docx openpyxl python-pptx pypdf numpy
.venv\Scripts\pip install "huggingface_hub<1.0"   # fw 1.1.x 兼容
```

注意：不要用 PyAV 直接解码音频（本机存在 av/faster-whisper 版本兼容坑），
read_evidence.py 已改为 ffmpeg→PCM→whisper 管线。
