# -*- coding: utf-8 -*-
"""图片与扫描件 OCR（可选，懒加载，可开关）

轻量路线：用 rapidocr_onnxruntime（ONNX，无 torch），与现有 onnxruntime 共存。
未安装或模型缺失时抛错由调用方转成友好提示，不阻断主链路。
图片直接识别；扫描型 PDF 由 loader 按页渲染后逐页识别。
"""

import sys
from pathlib import Path


def available() -> bool:
    try:
        import rapidocr_onnxruntime  # noqa: F401
        from PIL import Image  # noqa: F401

        return True
    except Exception:
        return False


def ocr_image(path: str | Path) -> str:
    """识别单张图片，返回拼接文本"""
    try:
        from rapidocr_onnxruntime import RapidOCR
        from PIL import Image
    except Exception as exc:
        raise RuntimeError(f"OCR 引擎未安装，需 pip install rapidocr_onnxruntime pillow：{exc}")
    engine = RapidOCR()
    img = Image.open(path)
    result, _ = engine(img)
    if not result:
        return ""
    # result 为 [box, text, conf] 列表
    lines = [r[1] for r in result if len(r) > 1 and r[1]]
    return "\n".join(lines)


def ocr_pdf_scanned(path: str | Path, max_pages: int = 20, dpi: int = 150) -> str:
    """扫描型 PDF 按页渲染后 OCR，返回带页码文本"""
    try:
        import pypdfium2 as pdfium
    except Exception as exc:
        raise RuntimeError(f"PDF 渲染依赖缺失：{exc}")
    if not available():
        raise RuntimeError("OCR 引擎未安装，需 pip install rapidocr_onnxruntime pillow")
    from rapidocr_onnxruntime import RapidOCR

    engine = RapidOCR()
    pdf = pdfium.PdfDocument(str(path))
    scale = dpi / 72.0
    out: list[str] = []
    for i, page in enumerate(pdf):
        if i >= max_pages:
            out.append(f"【第 {i + 1} 页起略：超 {max_pages} 页上限】")
            break
        try:
            bitmap = page.render(scale=scale).to_pil()
            result, _ = engine(bitmap)
            lines = [r[1] for r in (result or []) if len(r) > 1 and r[1]]
            if lines:
                out.append(f"【第 {i + 1} 页】\n" + "\n".join(lines))
        except Exception as exc:
            print(f"[ocr] 第 {i + 1} 页识别失败，已跳过：{exc}", file=sys.stderr)
    return "\n\n".join(out)
