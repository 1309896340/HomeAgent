"""技能注册表：扫描 skills/agent/ 目录，解析 SKILL.md frontmatter。

目录约定（与开发流程技能隔离）：
  skills/agent/  对话 Agent 的运行时技能（本注册表唯一来源）
  skills/dev/    项目开发流程技能（供开发助手使用，对话不可见）

渐进式披露三层中的前两层：
  1. list_skills()  —— 仅 name + description，供 system prompt 注入（常驻成本极低）
  2. read_skill()   —— 模型通过 read_skill 工具按需读取正文

格式约定：技能 = skills/agent/<name>/SKILL.md，文件必须以 YAML frontmatter
开头（首行 ---），frontmatter 含 name 与 description；不合规文件跳过并告警。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import yaml

from web.backend.config import settings

logger = logging.getLogger(__name__)

SKILL_BODY_MAX_CHARS = 30_000


def _parse_skill_file(path: Path) -> dict | None:
    """解析单个 SKILL.md，返回 {name, description}；不合规返回 None。"""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        logger.warning("技能文件读取失败 %s: %s", path, e)
        return None
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end < 0:
        return None
    try:
        meta = yaml.safe_load(text[3:end]) or {}
    except yaml.YAMLError as e:
        logger.warning("技能 frontmatter 解析失败 %s: %s", path, e)
        return None
    if not isinstance(meta, dict):
        return None
    name = str(meta.get("name") or "").strip()
    description = str(meta.get("description") or "").strip()
    if not name or not description:
        return None
    return {"name": name, "description": description}


def list_skills() -> list[dict]:
    """扫描技能目录，返回 [{name, description}]。

    每次调用重新扫描：本地文件 glob 开销微乎其微，换取技能热更新。
    """
    skills: list[dict] = []
    root = settings.skills_dir
    if not root.is_dir():
        return skills
    for path in sorted(root.glob("*/SKILL.md")):
        meta = _parse_skill_file(path)
        if meta is None:
            logger.warning("跳过不合规技能文件: %s", path)
            continue
        skills.append(meta)
    return skills


def read_skill(name: str) -> str:
    """读取技能正文；技能不存在或名字非法抛 FileNotFoundError。"""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", name):
        # 技能名限定为目录安全的短标识，防止路径穿越
        raise FileNotFoundError(f"非法技能名: {name!r}")
    path = settings.skills_dir / name / "SKILL.md"
    if not path.is_file():
        available = ", ".join(s["name"] for s in list_skills()) or "(无)"
        raise FileNotFoundError(f"技能不存在: {name}。可用技能: {available}")
    text = path.read_text(encoding="utf-8")
    if len(text) > SKILL_BODY_MAX_CHARS:
        text = text[:SKILL_BODY_MAX_CHARS] + "\n…（正文过长已截断）"
    return text
