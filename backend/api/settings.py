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
