# -*- coding: utf-8 -*-
"""合规自查取证工具（智能体经 exec 调用）。逐字抽取，不做任何加工润色。

用法:
    python read_evidence.py <文件路径> [--max-chars N]

支持: 纯文本(txt/md/csv/json/xml/html)、docx/xlsx/pptx/pdf/rtf/eml/zip/odt/ods/vsdx、
      mp3/wav/m4a/flac/ogg/aac（本地 faster-whisper 语音转写，逐字原文）。
输出: 逐字文本到 stdout。失败输出以 ERROR: 开头的原因（非零退出码）。
"""
import sys
import re
import os as _os
import zipfile
from pathlib import Path

TEXT_EXT = {".txt", ".md", ".csv", ".log", ".json", ".xml", ".html", ".htm"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac", ".wma", ".amr"}


def fail(msg: str):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(2)


def plain_text(data: bytes) -> str:
    return data.decode("utf-8", "replace")


def read_docx(p: Path) -> str:
    from docx import Document
    d = Document(str(p))
    parts = [para.text for para in d.paragraphs if para.text.strip()]
    for t in d.tables:
        for row in t.rows:
            parts.append(" | ".join(c.text.strip() for c in row.cells))
    return "\n".join(parts)


def read_xlsx(p: Path) -> str:
    from openpyxl import load_workbook
    wb = load_workbook(str(p), read_only=True, data_only=True)
    out = []
    for ws in wb.worksheets:
        out.append(f"[工作表] {ws.title}")
        for row in ws.iter_rows(values_only=True):
            cells = [str(c) for c in row if c is not None]
            if cells:
                out.append(" | ".join(cells))
    wb.close()
    return "\n".join(out)


def read_pptx(p: Path) -> str:
    from pptx import Presentation
    pr = Presentation(str(p))
    out = []
    for i, slide in enumerate(pr.slides, 1):
        texts = []
        for sh in slide.shapes:
            if sh.has_text_frame:
                texts.append(sh.text_frame.text)
            if getattr(sh, "has_table", False) and sh.has_table:
                for row in sh.table.rows:
                    texts.append(" | ".join(c.text for c in row.cells))
        out.append(f"[幻灯片 {i}]\n" + "\n".join(t for t in texts if t.strip()))
    return "\n".join(out)


def read_pdf(p: Path) -> str:
    from pypdf import PdfReader
    r = PdfReader(str(p))
    return "\n".join((pg.extract_text() or "") for pg in r.pages)


def read_rtf(p: Path) -> str:
    raw = plain_text(p.read_bytes())
    txt = re.sub(r"\\[a-z]+-?\d* ?", " ", raw)
    txt = re.sub(r"[{}]", "", txt)
    return txt


def read_eml(p: Path) -> str:
    import email
    from email import policy
    m = email.message_from_binary_file(p.open("rb"), policy=policy.default)
    parts = [f"主题:{m.get('subject','')} 发件:{m.get('from','')} 日期:{m.get('date','')}"]
    body = m.get_body(preferencelist=("plain", "html"))
    if body:
        parts.append(body.get_content())
    return "\n".join(parts)


def read_zip(p: Path) -> str:
    out = []
    with zipfile.ZipFile(p) as z:
        names = z.namelist()
        out.append("[压缩包目录] " + "; ".join(names))
        for n in names:
            if n.endswith((".txt", ".md", ".csv", ".log")):
                try:
                    out.append(f"--- {n} ---\n" + plain_text(z.read(n)))
                except Exception:
                    pass
    return "\n".join(out)


def read_office_xml(p: Path) -> str:
    with zipfile.ZipFile(p) as z:
        names = z.namelist()
        main = next((n for n in names if n == "content.xml"),
                    next((n for n in names if n.endswith(".xml")
                          and ("document" in n or n.startswith("visio/"))), None))
        if not main:
            fail("zip-XML 容器找不到主文档")
        x = plain_text(z.read(main))
    x = re.sub(r"<[^>]+>", " ", x)
    return re.sub(r"\s+", " ", x)


def _find_ffmpeg() -> str:
    import glob as _glob
    c = _os.environ.get("FFMPEG") or ""
    if c and _os.path.exists(c):
        return c
    c = __import__("shutil").which("ffmpeg") or __import__("shutil").which("ffmpeg.exe")
    if c:
        return c
    pats = [
        _os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\*FFmpeg*\**\bin\ffmpeg.exe"),
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"D:\program\ffmpeg*\bin\ffmpeg.exe",
    ]
    for pat in pats:
        hits = _glob.glob(pat)
        if hits:
            return hits[0]
    return ""


def read_audio(p: Path) -> str:
    import subprocess
    import numpy as np
    _os.environ.setdefault("HF_HUB_OFFLINE", "1")
    ff = _find_ffmpeg()
    if not ff:
        fail("未找到 ffmpeg（语音转写需要）；可设环境变量 FFMPEG=<ffmpeg.exe 路径>")
    # ffmpeg 解码为 16k 单声道 PCM 后逐字转写（绕开 PyAV 兼容问题）
    r = subprocess.run([ff, "-v", "error", "-i", str(p), "-ac", "1", "-ar", "16000",
                        "-f", "s16le", "-"], capture_output=True, timeout=300)
    if r.returncode != 0 or not r.stdout:
        fail(f"音频解码失败：{r.stderr.decode('utf-8','replace')[:120]}")
    from faster_whisper import WhisperModel
    pcm = np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32) / 32768.0
    model = WhisperModel("small", device="cpu", compute_type="int8")
    segs, info = model.transcribe(pcm, language="zh", beam_size=1)
    out = [f"[转写元数据] 语言={info.language} 时长={info.duration:.1f}s（逐字原文，未经任何加工）"]
    for s in segs:
        out.append(f"[{s.start:.1f}s-{s.end:.1f}s] {s.text}")
    return "\n".join(out)


def main():
    if len(sys.argv) < 2:
        fail("用法: python read_evidence.py <文件路径> [--max-chars N]")
    p = Path(sys.argv[1])
    max_chars = 60000
    if "--max-chars" in sys.argv:
        try:
            max_chars = int(sys.argv[sys.argv.index("--max-chars") + 1])
        except Exception:
            pass
    if not p.exists():
        fail(f"文件不存在: {p}")
    ext = p.suffix.lower()
    try:
        if ext in TEXT_EXT:
            text = plain_text(p.read_bytes())
        elif ext == ".docx":
            text = read_docx(p)
        elif ext in (".xlsx", ".xlsm"):
            text = read_xlsx(p)
        elif ext == ".pptx":
            text = read_pptx(p)
        elif ext == ".pdf":
            text = read_pdf(p)
        elif ext == ".rtf":
            text = read_rtf(p)
        elif ext == ".eml":
            text = read_eml(p)
        elif ext == ".zip":
            text = read_zip(p)
        elif ext in (".odt", ".ods", ".odp", ".vsdx", ".drawio"):
            text = read_office_xml(p)
        elif ext in AUDIO_EXT:
            text = read_audio(p)
        elif ext in (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"):
            fail("图片请用 read 工具直接读取（你的视觉能力可直接理解图片内容），不要用电文工具。")
        else:
            fail(f"暂不支持的格式: {ext}")
    except Exception as e:
        fail(f"解析失败: {type(e).__name__}: {e}")
    if not text.strip():
        print("WARN: 文件解析结果为空（可能是扫描件或纯图 PDF）")
        return
    print(text[:max_chars])
    if len(text) > max_chars:
        print(f"…（超出 {max_chars} 字符已截断，可用 --max-chars 调大或分段处理）")


if __name__ == "__main__":
    main()
