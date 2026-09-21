# -*- coding: utf-8 -*-
"""Embedder 的行为约束测试

只覆盖「改错了会静默出问题」的逻辑，不做模型推理的端到端断言
（那依赖网络与模型文件，不适合作为单测）。

为什么这几条值得测：
    1. HF 环境变量若用 os.environ.setdefault 设置，会被外部残留值覆盖，
       导致模型下载走回镜像不支持的 Xet 协议并失败——表现为「有时能下载
       有时不能」，极难定位。
    2. state 三态若退化成单一的 available 布尔值，用户就无法区分
       「还没试过」与「试过但失败了」，前端提示文案会失去依据。
    3. Embedder 若退回「每个检索器各建一个」，N 个知识库会重复常驻
       N 份模型权重（每份约 90 MB）。

运行：backend/.venv/Scripts/python -m unittest discover -s backend/tests -v
"""

import os
import subprocess
import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
PYTHON = BACKEND_DIR / ".venv" / "Scripts" / "python.exe"
if not PYTHON.exists():
    PYTHON = BACKEND_DIR / ".venv" / "bin" / "python"

# 在子进程里探查环境变量：模块导入时的赋值只发生一次，
# 必须在全新解释器中验证，否则会被本进程已有的环境干扰。
_ENV_PROBE = """
import sys
sys.path.insert(0, r"{backend}")
import core.embedder  # noqa: F401  —— 导入即完成环境变量设置
import os
print("HF_ENDPOINT=" + str(os.environ.get("HF_ENDPOINT")))
print("HF_HUB_DISABLE_XET=" + str(os.environ.get("HF_HUB_DISABLE_XET")))
"""


class HFEnvOverrideTest(unittest.TestCase):
    """HF 镜像与 Xet 协议的强制覆盖

    这两项不是「用户偏好」而是「绕过已知故障的必需开关」：
    镜像不支持 Xet 协议、Google 存储桶不可达。被外部环境残留值覆盖时，
    下载会失败并静默退化成 BM25 单路。
    """

    def _probe(self, extra_env: dict) -> dict:
        env = {**os.environ, **extra_env, "PYTHONIOENCODING": "utf-8"}
        proc = subprocess.run(
            [str(PYTHON), "-c", _ENV_PROBE.format(backend=BACKEND_DIR)],
            env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=180,
        )
        self.assertEqual(proc.returncode, 0, f"子进程失败：{proc.stderr[-500:]}")
        out = {}
        for line in proc.stdout.splitlines():
            if "=" in line and not line.startswith(" "):
                k, _, v = line.partition("=")
                if k.startswith("HF_"):
                    out[k] = v
        out["_stderr"] = proc.stderr or ""
        return out

    def test_defaults_applied_when_env_clean(self):
        """环境干净时应设为镜像地址并禁用 Xet"""
        r = self._probe({})
        self.assertEqual(r["HF_ENDPOINT"], "https://hf-mirror.com")
        self.assertEqual(r["HF_HUB_DISABLE_XET"], "1")

    def test_stale_env_is_overridden(self):
        """外部残留的错误值必须被纠正，否则下载会走回不可用的 Xet 协议

        这是本测试的核心：若把实现改回 os.environ.setdefault，此用例会失败。
        """
        r = self._probe({"HF_HUB_DISABLE_XET": "0",
                         "HF_ENDPOINT": "https://huggingface.co"})
        self.assertEqual(r["HF_HUB_DISABLE_XET"], "1",
                         "残留值未被覆盖，模型下载会失败")
        self.assertEqual(r["HF_ENDPOINT"], "https://hf-mirror.com",
                         "残留值未被覆盖")

    def test_override_is_logged(self):
        """覆盖用户环境变量时必须留下日志，不做无声改变"""
        r = self._probe({"HF_HUB_DISABLE_XET": "0"})
        self.assertIn("覆盖环境变量", r["_stderr"])

    def test_no_noise_when_values_already_correct(self):
        """值本来就对时不该产生日志噪音"""
        r = self._probe({"HF_HUB_DISABLE_XET": "1",
                         "HF_ENDPOINT": "https://hf-mirror.com"})
        self.assertNotIn("覆盖环境变量", r["_stderr"])


class EmbedderStateTest(unittest.TestCase):
    """三态状态机：idle / ready / failed

    单看 available 分不清「还没试过」与「试过但失败了」——
    对用户来说前者需等待、后者需修配置，前端提示文案完全不同。
    """

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(BACKEND_DIR))

    def test_initial_state_is_idle(self):
        """新建实例尚未尝试加载，应为 idle 而非 failed"""
        from core.embedder import Embedder
        e = Embedder()
        self.assertEqual(e.state, "idle")
        self.assertFalse(e.available)
        self.assertEqual(e.error, "")

    def test_failed_state_records_reason(self):
        """加载失败应转为 failed 并留下可上报的原因"""
        from core.embedder import Embedder
        e = Embedder(model_name="definitely-not-a-real-model-xyz")
        self.assertFalse(e.warmup())
        self.assertEqual(e.state, "failed")
        self.assertFalse(e.available)
        self.assertTrue(e.error, "失败原因不应为空，否则前端无法给出提示")

    def test_warmup_failure_does_not_raise(self):
        """预热失败不能抛异常——向量不可用只是降级，不该阻断服务启动"""
        from core.embedder import Embedder
        e = Embedder(model_name="definitely-not-a-real-model-xyz")
        try:
            e.warmup()
        except Exception as exc:  # noqa: BLE001
            self.fail(f"warmup() 不应抛出异常，实际抛出 {type(exc).__name__}")

    def test_failed_state_is_sticky(self):
        """失败后不反复重试，避免每次检索都拖累"""
        from core.embedder import Embedder
        e = Embedder(model_name="definitely-not-a-real-model-xyz")
        e.warmup()
        first = e.error
        e.warmup()
        self.assertEqual(e.error, first, "重复预热不应改变已记录的失败原因")


class EmbedderSingletonTest(unittest.TestCase):
    """模型权重必须进程内共享一份

    每个 VectorRetriever 各建一个 Embedder 会让 N 个知识库
    重复常驻 N 份权重（每份约 90 MB），且 health 上报无从选择读取对象。
    """

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(BACKEND_DIR))

    def test_get_embedder_returns_same_instance(self):
        from core.embedder import get_embedder
        self.assertIs(get_embedder(), get_embedder())

    def test_retrievers_share_embedder(self):
        from core.retriever import HybridRetriever
        a, b = HybridRetriever(), HybridRetriever()
        self.assertIs(a.vector.embedder, b.vector.embedder,
                      "多个检索器应共用同一 Embedder 实例")

    def test_manager_vector_status_reads_global_singleton(self):
        """health 读的应是全局状态，与某个知识库索引是否已构建无关"""
        from core.embedder import get_embedder
        from core.manager import KBManager
        status = KBManager().vector_status()
        self.assertEqual(status["state"], get_embedder().state)
        self.assertIn(status["state"], ("idle", "ready", "failed"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
