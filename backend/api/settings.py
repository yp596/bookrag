# -*- coding: utf-8 -*-
"""模型配置接口"""

from fastapi import APIRouter
from pydantic import BaseModel

from api.deps import settings_store
from core.llm import LLMClient

router = APIRouter(prefix="/api/settings", tags=["设置"])


class SettingsPayload(BaseModel):
    """允许前端提交的配置项，未提供的字段保持不变"""

    llm_mode: str | None = None
    local: dict | None = None
    cloud: dict | None = None
    top_k: int | None = None
    chunk_size: int | None = None
    chunk_overlap: int | None = None
    cross_rerank_enabled: bool | None = None


@router.get("")
def get_settings() -> dict:
    """读取当前配置"""
    return settings_store.get()


@router.post("")
def save_settings(payload: SettingsPayload) -> dict:
    """保存配置（仅白名单字段生效）"""
    data = payload.model_dump(exclude_none=True)
    return settings_store.save(data)


@router.post("/test")
def test_connection() -> dict:
    """测试当前模式的模型连通性"""
    profile = settings_store.get_llm_profile()
    client = LLMClient(
        mode=profile["mode"],
        base_url=profile["base_url"],
        api_key=profile["api_key"],
        model=profile["model"],
    )
    ok, message = client.test_connection()
    return {"ok": ok, "message": message, "mode": profile["mode"], "model": profile["model"]}


@router.get("/local-model")
def local_model_status() -> dict:
    """本地模型 sidecar 状态：二进制与权重是否存在、服务是否存活"""
    from core.local_model import check_health, status

    info = status()
    info["serving"] = check_health()
    return info


class DirectTestPayload(BaseModel):
    """临时测试：通过密钥和链接直接获取大模型"""

    api_key: str
    base_url: str
    model: str


@router.post("/test-direct")
def test_direct(payload: DirectTestPayload) -> dict:
    """临时测试：不保存配置，直接用用户传入的参数测试 LLM 连通性"""
    client = LLMClient(
        mode="cloud",
        base_url=payload.base_url,
        api_key=payload.api_key,
        model=payload.model,
    )
    ok, message = client.test_connection()
    return {"ok": ok, "message": message, "model": payload.model}
