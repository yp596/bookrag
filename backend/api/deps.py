# -*- coding: utf-8 -*-
"""API 依赖

集中提供全局单例，避免各路由重复构造。
"""

from core.manager import KBManager
from core.settings_store import SettingsStore
from core.storage import Storage

storage = Storage()
kb_manager = KBManager(storage)
settings_store = SettingsStore()
