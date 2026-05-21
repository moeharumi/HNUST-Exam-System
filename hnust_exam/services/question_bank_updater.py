"""题库静默更新服务：后台检测 GitHub 题库文件变更并自动下载.

设计原则：
- 全程静默：任何网络异常、解析失败都不抛到 UI 层
- 原子写入：下载到 .tmp 文件后 rename，防止文件损坏
- 增量更新：只下载新增或 SHA 变化的文件
- 去抖保护：每小时最多检测一次，避免频繁调用 GitHub API
"""

from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Thread

import requests

from hnust_exam.utils.constants import (
    GITHUB_REPO_NAME,
    GITHUB_USERNAME,
    MANIFEST_FILE,
    QUESTION_BANK_DIR,
    QUESTION_BANK_FILES_DIR,
)

# ── 常量 ──────────────────────────────────────────────────────────

_LAST_CHECK_FILE = os.path.join(QUESTION_BANK_DIR, "last_check")
_CHECK_INTERVAL = 3600  # 秒，两次检测最小间隔
_API_TIMEOUT = 10  # API 请求超时
_DOWNLOAD_TIMEOUT = 30  # 文件下载超时
_MAX_WORKERS = 4  # 并行下载数


# ── GitHub API 交互 ──────────────────────────────────────────────

def _fetch_remote_file_list() -> list[dict] | None:
    """递归获取 GitHub 上 题库/ 目录的所有文件信息.

    Returns: [{rel_path, sha, download_url}, ...] 或 None（网络/解析失败）
    """
    files: list[dict] = []
    try:
        with requests.Session() as session:
            session.headers.update({"Accept": "application/vnd.github.v3+json"})
            if not _list_files_recursive(session, "题库", files):
                return None
        return files
    except Exception:
        return None


def _list_files_recursive(
    session: requests.Session, api_path: str, files: list[dict],
) -> bool:
    """递归列出目录下所有文件信息，追加到 files 列表."""
    url = (
        f"https://api.github.com/repos/{GITHUB_USERNAME}"
        f"/{GITHUB_REPO_NAME}/contents/{api_path}"
    )
    try:
        resp = session.get(url, timeout=_API_TIMEOUT)
        resp.raise_for_status()
        items = resp.json()
        if not isinstance(items, list):
            return True

        for item in items:
            item_path: str = item.get("path", "")
            item_type: str = item.get("type", "")
            rel_path = item_path
            if rel_path.startswith("题库/"):
                rel_path = rel_path[len("题库/"):]

            if item_type == "file":
                files.append({
                    "rel_path": rel_path,
                    "sha": item.get("sha", ""),
                    "download_url": item.get("download_url", ""),
                })
            elif item_type == "dir":
                sub_path = item_path.lstrip("/")
                if not _list_files_recursive(session, sub_path, files):
                    return False
        return True
    except Exception:
        return False


# ── Manifest 管理 ─────────────────────────────────────────────────

def _load_local_manifest() -> dict[str, str]:
    """加载本地 manifest.json，返回 {rel_path: sha}."""
    try:
        if os.path.isfile(MANIFEST_FILE):
            with open(MANIFEST_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_local_manifest(manifest: dict[str, str]) -> None:
    """原子写入 manifest.json（先写 .tmp 再 rename）."""
    try:
        os.makedirs(os.path.dirname(MANIFEST_FILE), exist_ok=True)
        tmp = MANIFEST_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        os.replace(tmp, MANIFEST_FILE)
    except Exception:
        pass


# ── 文件下载 ───────────────────────────────────────────────────────

def _download_file(rel_path: str, download_url: str) -> bool:
    """下载单个文件到本地缓存，原子写入。成功返回 True."""
    if not download_url:
        return False
    target = os.path.join(QUESTION_BANK_FILES_DIR, "题库", rel_path)
    tmp = target + ".tmp"
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        resp = requests.get(download_url, timeout=_DOWNLOAD_TIMEOUT)
        resp.raise_for_status()
        with open(tmp, "wb") as f:
            f.write(resp.content)
        os.replace(tmp, target)
        return True
    except Exception:
        try:
            if os.path.isfile(tmp):
                os.remove(tmp)
        except Exception:
            pass
        return False


# ── 限速 (去抖) ────────────────────────────────────────────────────

def _should_check() -> bool:
    """判断是否需要进行检测（距上次检测超过 1 小时）."""
    try:
        if os.path.isfile(_LAST_CHECK_FILE):
            with open(_LAST_CHECK_FILE, "r") as f:
                last = float(f.read().strip())
            if time.time() - last < _CHECK_INTERVAL:
                return False
    except Exception:
        pass
    return True


def _mark_checked() -> None:
    """记录本次检测时间."""
    try:
        os.makedirs(os.path.dirname(_LAST_CHECK_FILE), exist_ok=True)
        with open(_LAST_CHECK_FILE, "w") as f:
            f.write(str(time.time()))
    except Exception:
        pass


# ── 主同步逻辑 ─────────────────────────────────────────────────────

def _sync_question_bank() -> None:
    """核心同步：对比远程和本地 manifest，下载差异文件."""
    # 1. 获取远程文件列表
    remote_files = _fetch_remote_file_list()
    if remote_files is None:
        return

    # 2. 构建远程 SHA 映射
    remote_manifest: dict[str, str] = {}
    for f in remote_files:
        if f["download_url"]:
            remote_manifest[f["rel_path"]] = f["sha"]
    if not remote_manifest:
        return

    # 3. 对比本地 manifest
    local_manifest = _load_local_manifest()

    # 4. 找出需要下载的文件
    to_download = [
        f for f in remote_files
        if f["rel_path"] in remote_manifest
        and local_manifest.get(f["rel_path"]) != f["sha"]
    ]
    if not to_download:
        return

    # 5. 并行下载
    successful: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as executor:
        future_map = {
            executor.submit(_download_file, f["rel_path"], f["download_url"]): f
            for f in to_download
        }
        for future in as_completed(future_map):
            f = future_map[future]
            if future.result():
                successful[f["rel_path"]] = f["sha"]

    # 6. 更新 manifest（仅记录成功下载的文件）
    if successful:
        new_manifest = {**local_manifest, **successful}
        _save_local_manifest(new_manifest)


# ── 公开入口 ───────────────────────────────────────────────────────

def check_question_bank_update_async() -> None:
    """静默检查并更新题库（后台线程，幂等安全，可重复调用）."""
    if not _should_check():
        return

    def _worker() -> None:
        try:
            _mark_checked()  # 先标记，防止同次启动重复检查
            _sync_question_bank()
        except Exception:
            pass

    Thread(target=_worker, daemon=True).start()
