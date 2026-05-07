from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
import json
import threading
import uuid
from pathlib import Path
from typing import Any

from services.account_service import account_service
from services.auth_service import _write_text_atomically
from services.config import DATA_DIR
from services.register.openai_register import register_once
from services.register.mail_provider import validate_mail_config

REGISTER_FILE = DATA_DIR / "register.json"
REGISTER_MODES = {"total", "quota", "available"}
REGISTER_FAILURE_BACKOFF_TRIGGER = 2
REGISTER_FAILURE_BACKOFF_BASE_SECONDS = 5.0
REGISTER_FAILURE_BACKOFF_MAX_SECONDS = 60.0


def _now_text() -> str:
    return datetime.now(timezone.utc).isoformat()


def _deep_copy(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _clean_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _clean_int(value: Any, *, fallback: int, min_value: int, max_value: int) -> int:
    if value in (None, ""):
        return fallback
    try:
        numeric = int(float(value))
    except (TypeError, ValueError):
        return fallback
    return max(min_value, min(max_value, numeric))


def _default_mail_config() -> dict[str, Any]:
    return {
        "request_timeout": 30,
        "wait_timeout": 180,
        "wait_interval": 2,
        "providers": [],
    }


def _default_stats(threads: int) -> dict[str, Any]:
    return {
        "job_id": "",
        "success": 0,
        "fail": 0,
        "done": 0,
        "running": 0,
        "threads": threads,
        "elapsed_seconds": 0.0,
        "avg_seconds": 0.0,
        "success_rate": 0.0,
        "current_quota": 0,
        "current_available": 0,
        "started_at": "",
        "updated_at": _now_text(),
        "finished_at": "",
    }


def _default_config() -> dict[str, Any]:
    threads = 1
    return {
        "enabled": False,
        "mail": _default_mail_config(),
        "proxy": "",
        "total": 10,
        "threads": threads,
        "mode": "total",
        "target_quota": 100,
        "target_available": 10,
        "check_interval": 5,
        "stats": _default_stats(threads),
        "logs": [],
    }


def _failure_backoff_seconds(consecutive_failures: int) -> float:
    if consecutive_failures < REGISTER_FAILURE_BACKOFF_TRIGGER:
        return 0.0
    exponent = consecutive_failures - REGISTER_FAILURE_BACKOFF_TRIGGER
    return min(REGISTER_FAILURE_BACKOFF_MAX_SECONDS, REGISTER_FAILURE_BACKOFF_BASE_SECONDS * (2**exponent))


def _normalize_provider(raw: object) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    domains_value = raw.get("domains")
    if domains_value is None:
        domains_value = raw.get("domain")
    domains: list[str] = []
    if isinstance(domains_value, list):
        domains = [item for item in (_clean_text(item) for item in domains_value) if item]
    elif isinstance(domains_value, str):
        domains = [item for item in (_clean_text(part) for part in domains_value.split(",")) if item]
    return {
        "id": _clean_text(raw.get("id")) or uuid.uuid4().hex[:8],
        "type": _clean_text(raw.get("type")) or "generic",
        "enabled": _clean_bool(raw.get("enabled", raw.get("enable", True))),
        "api_key": _clean_text(raw.get("api_key")),
        "api_base": _clean_text(raw.get("api_base")),
        "admin_password": _clean_text(raw.get("admin_password")),
        "default_domain": _clean_text(raw.get("default_domain")),
        "expiry_time": _clean_int(raw.get("expiry_time"), fallback=0, min_value=0, max_value=31_536_000),
        "random_subdomain": True if raw.get("random_subdomain") is None else _clean_bool(raw.get("random_subdomain")),
        "subdomain": _clean_text(raw.get("subdomain")),
        "wildcard": _clean_bool(raw.get("wildcard")),
        "domains": domains,
    }


def _normalize_mail_config(raw: object) -> dict[str, Any]:
    default = _default_mail_config()
    if not isinstance(raw, dict):
        return default
    providers: list[dict[str, Any]] = []
    if isinstance(raw.get("providers"), list):
        for item in raw["providers"]:
            provider = _normalize_provider(item)
            if provider is not None:
                providers.append(provider)
    return {
        "request_timeout": _clean_int(raw.get("request_timeout"), fallback=default["request_timeout"], min_value=1, max_value=3600),
        "wait_timeout": _clean_int(raw.get("wait_timeout"), fallback=default["wait_timeout"], min_value=1, max_value=3600),
        "wait_interval": _clean_int(raw.get("wait_interval"), fallback=default["wait_interval"], min_value=1, max_value=300),
        "providers": providers,
    }


def _normalize_logs(raw: object) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    items: list[dict[str, str]] = []
    for item in raw[-300:]:
        if not isinstance(item, dict):
            continue
        items.append(
            {
                "time": _clean_text(item.get("time")) or _now_text(),
                "text": _clean_text(item.get("text")),
                "level": _clean_text(item.get("level")) or "info",
            }
        )
    return items


def _normalize_config(raw: object) -> dict[str, Any]:
    config = _default_config()
    if not isinstance(raw, dict):
        return config

    config["mail"] = _normalize_mail_config(raw.get("mail"))
    config["proxy"] = _clean_text(raw.get("proxy"))
    config["total"] = _clean_int(raw.get("total"), fallback=config["total"], min_value=1, max_value=10_000)
    config["threads"] = _clean_int(raw.get("threads"), fallback=config["threads"], min_value=1, max_value=32)

    mode = _clean_text(raw.get("mode")) or config["mode"]
    config["mode"] = mode if mode in REGISTER_MODES else "total"
    config["target_quota"] = _clean_int(raw.get("target_quota"), fallback=config["target_quota"], min_value=1, max_value=1_000_000)
    config["target_available"] = _clean_int(
        raw.get("target_available"),
        fallback=config["target_available"],
        min_value=1,
        max_value=100_000,
    )
    config["check_interval"] = _clean_int(raw.get("check_interval"), fallback=config["check_interval"], min_value=1, max_value=3600)
    config["enabled"] = _clean_bool(raw.get("enabled"))

    default_stats = _default_stats(config["threads"])
    raw_stats = raw.get("stats") if isinstance(raw.get("stats"), dict) else {}
    config["stats"] = {
        **default_stats,
        "job_id": _clean_text(raw_stats.get("job_id")),
        "success": _clean_int(raw_stats.get("success"), fallback=0, min_value=0, max_value=1_000_000),
        "fail": _clean_int(raw_stats.get("fail"), fallback=0, min_value=0, max_value=1_000_000),
        "done": _clean_int(raw_stats.get("done"), fallback=0, min_value=0, max_value=1_000_000),
        "running": _clean_int(raw_stats.get("running"), fallback=0, min_value=0, max_value=config["threads"]),
        "threads": config["threads"],
        "elapsed_seconds": float(raw_stats.get("elapsed_seconds") or 0),
        "avg_seconds": float(raw_stats.get("avg_seconds") or 0),
        "success_rate": float(raw_stats.get("success_rate") or 0),
        "current_quota": _clean_int(raw_stats.get("current_quota"), fallback=0, min_value=0, max_value=1_000_000_000),
        "current_available": _clean_int(raw_stats.get("current_available"), fallback=0, min_value=0, max_value=1_000_000),
        "started_at": _clean_text(raw_stats.get("started_at")),
        "updated_at": _clean_text(raw_stats.get("updated_at")) or default_stats["updated_at"],
        "finished_at": _clean_text(raw_stats.get("finished_at")),
    }
    config["logs"] = _normalize_logs(raw.get("logs"))
    return config


class RegisterService:
    def __init__(self, store_file: Path, accounts_service=account_service, executor=register_once):
        self._store_file = store_file
        self._account_service = accounts_service
        self._executor = executor
        self._lock = threading.RLock()
        self._runner: threading.Thread | None = None
        self._stop_event: threading.Event | None = None
        self._config = self._load()
        self._restore_runner_if_enabled()

    def _load(self) -> dict[str, Any]:
        try:
            return _normalize_config(json.loads(self._store_file.read_text(encoding="utf-8")))
        except Exception:
            return _normalize_config({})

    def _save_locked(self) -> None:
        _write_text_atomically(
            self._store_file,
            json.dumps(self._config, ensure_ascii=False, indent=2) + "\n",
        )

    def _pool_metrics(self) -> dict[str, int]:
        items = self._account_service.list_accounts()
        normal_items = [item for item in items if item.get("status") == "正常"]
        known_quota_items = [item for item in normal_items if not item.get("imageQuotaUnknown")]
        return {
            "current_quota": sum(max(0, int(item.get("quota") or 0)) for item in known_quota_items),
            "current_available": len(normal_items),
        }

    def _refresh_stats_locked(self) -> None:
        stats = self._config["stats"]
        stats["threads"] = self._config["threads"]
        stats.update(self._pool_metrics())
        started_at = _clean_text(stats.get("started_at"))
        if started_at:
            try:
                started = datetime.fromisoformat(started_at)
                elapsed = max(0.0, (datetime.now(timezone.utc) - started).total_seconds())
            except ValueError:
                elapsed = 0.0
            stats["elapsed_seconds"] = round(elapsed, 1)
            success = max(0, int(stats.get("success") or 0))
            fail = max(0, int(stats.get("fail") or 0))
            stats["avg_seconds"] = round(elapsed / success, 1) if success else 0.0
            stats["success_rate"] = round(success * 100 / max(1, success + fail), 1)
        stats["updated_at"] = _now_text()

    def _append_log_locked(self, text: str, level: str = "info") -> None:
        self._config["logs"].append(
            {
                "time": _now_text(),
                "text": _clean_text(text),
                "level": _clean_text(level) or "info",
            }
        )
        self._config["logs"] = self._config["logs"][-300:]

    def _snapshot_locked(self) -> dict[str, Any]:
        return _deep_copy(self._config)

    def _launch_runner_locked(self, *, reset_state: bool, log_message: str) -> None:
        self._config["enabled"] = True
        if reset_state:
            self._config["stats"] = {
                **_default_stats(self._config["threads"]),
                "job_id": uuid.uuid4().hex[:12],
                "started_at": _now_text(),
            }
            self._config["logs"] = []
        else:
            stats = self._config["stats"]
            if not _clean_text(stats.get("job_id")):
                stats["job_id"] = uuid.uuid4().hex[:12]
            if not _clean_text(stats.get("started_at")):
                stats["started_at"] = _now_text()
            stats["running"] = 0
            stats["finished_at"] = ""
        self._append_log_locked(log_message, "warning")
        self._refresh_stats_locked()
        stop_event = threading.Event()
        self._stop_event = stop_event
        self._runner = threading.Thread(
            target=self._run,
            args=(stop_event,),
            daemon=True,
            name="register-runner",
        )
        self._save_locked()
        self._runner.start()

    def _restore_runner_if_enabled(self) -> None:
        with self._lock:
            if not self._config.get("enabled"):
                return
            try:
                validate_mail_config(self._config["mail"])
            except RuntimeError as exc:
                self._config["enabled"] = False
                self._append_log_locked(f"注册 runner 自动恢复失败: {exc}", "warning")
                self._refresh_stats_locked()
                self._save_locked()
                return
            self._launch_runner_locked(
                reset_state=False,
                log_message="检测到上次注册 runner 未正常结束，服务启动后已自动恢复。",
            )

    def _executor_log(self, index: int, text: str, level: str = "info") -> None:
        with self._lock:
            self._append_log_locked(f"[任务{index}] {_clean_text(text)}", level)
            self._save_locked()

    def _target_status_locked(self, submitted: int) -> tuple[bool, str]:
        metrics = self._pool_metrics()
        self._config["stats"].update(metrics)
        mode = self._config["mode"]
        if mode == "quota":
            current = metrics["current_quota"]
            target = int(self._config["target_quota"])
            return current >= target, f"当前总额度 {current} / 目标额度 {target}"
        if mode == "available":
            current = metrics["current_available"]
            target = int(self._config["target_available"])
            return current >= target, f"当前可用账号 {current} / 目标可用账号 {target}"
        target = int(self._config["total"])
        return submitted >= target, f"已提交任务 {submitted} / 目标总数 {target}"

    def get(self) -> dict[str, Any]:
        with self._lock:
            self._refresh_stats_locked()
            return self._snapshot_locked()

    def update(self, updates: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            next_config = _deep_copy(self._config)
            next_config.update({key: value for key, value in updates.items() if key != "mail"})
            if isinstance(updates.get("mail"), dict):
                merged_mail = _deep_copy(next_config.get("mail") or {})
                merged_mail.update(updates["mail"])
                next_config["mail"] = merged_mail
            self._config = _normalize_config(next_config)
            self._refresh_stats_locked()
            self._save_locked()
            return self._snapshot_locked()

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self._runner is not None and self._runner.is_alive():
                return self._snapshot_locked()
            try:
                validate_mail_config(self._config["mail"])
            except RuntimeError as exc:
                raise ValueError(str(exc)) from exc
            self._launch_runner_locked(
                reset_state=True,
                log_message="注册 runner 已启动；当前阶段已接入 tempmail_lol / moemail 真实注册执行链路。",
            )
            return self._snapshot_locked()

    def stop(self) -> dict[str, Any]:
        with self._lock:
            self._config["enabled"] = False
            self._append_log_locked("已请求停止注册 runner。", "info")
            self._refresh_stats_locked()
            stop_event = self._stop_event
            self._save_locked()
            snapshot = self._snapshot_locked()
        if stop_event is not None:
            stop_event.set()
        return snapshot

    def reset(self) -> dict[str, Any]:
        with self._lock:
            if self._runner is not None and self._runner.is_alive():
                raise ValueError("register runner is active")
            self._config["enabled"] = False
            self._config["logs"] = []
            self._config["stats"] = _default_stats(self._config["threads"])
            self._refresh_stats_locked()
            self._save_locked()
            return self._snapshot_locked()

    def _run(self, stop_event: threading.Event) -> None:
        with self._lock:
            stats = self._config["stats"]
            done = max(0, int(stats.get("done") or 0))
            success = max(0, int(stats.get("success") or 0))
            fail = max(0, int(stats.get("fail") or 0))
            submitted = done
            self._config["stats"]["running"] = 0
            self._refresh_stats_locked()
            self._save_locked()
        waiting_logged = False
        consecutive_failures = 0
        pending_backoff_seconds = 0.0
        with ThreadPoolExecutor(max_workers=max(1, int(self._config["threads"]))) as executor:
            futures: dict[object, int] = {}
            while True:
                with self._lock:
                    threads = max(1, int(self._config["threads"]))
                    enabled = self._config["enabled"]
                    mode = self._config["mode"]
                    target_reached, target_summary = self._target_status_locked(submitted)
                    while enabled and not target_reached and len(futures) < threads:
                        submitted += 1
                        index = submitted
                        config_snapshot = self._snapshot_locked()
                        futures[executor.submit(self._executor, config_snapshot, lambda text, level="info", current=index: self._executor_log(current, text, level))] = index
                        target_reached, target_summary = self._target_status_locked(submitted)
                    if futures and waiting_logged and enabled and mode != "total":
                        self._append_log_locked(f"{target_summary}，低于目标，runner 已恢复补号。", "info")
                        waiting_logged = False
                    self._config["stats"]["done"] = done
                    self._config["stats"]["success"] = success
                    self._config["stats"]["fail"] = fail
                    self._config["stats"]["running"] = len(futures)
                    self._refresh_stats_locked()
                    self._save_locked()
                    enabled = self._config["enabled"]
                if not futures and (not enabled or (mode == "total" and pending_backoff_seconds <= 0)):
                    break
                if not futures:
                    if enabled and pending_backoff_seconds > 0:
                        delay = pending_backoff_seconds
                        pending_backoff_seconds = 0.0
                        if stop_event.wait(delay):
                            break
                        continue
                    if enabled and not waiting_logged and target_reached:
                        with self._lock:
                            self._append_log_locked(f"{target_summary}，runner 进入巡检等待；跌破目标后会自动恢复补号。", "info")
                            self._save_locked()
                        waiting_logged = True
                    if stop_event.wait(max(1, int(self._config.get("check_interval") or 5))):
                        break
                    continue
                finished, _ = wait(futures.keys(), return_when=FIRST_COMPLETED)
                for future in finished:
                    index = futures.pop(future)
                    try:
                        result = future.result()
                        access_token = _clean_text(result.get("access_token"))
                        email = _clean_text(result.get("email"))
                        if not access_token:
                            raise RuntimeError("executor did not return access_token")
                        self._account_service.add_accounts([access_token])
                        self._account_service.refresh_accounts([access_token])
                        done += 1
                        success += 1
                        consecutive_failures = 0
                        pending_backoff_seconds = 0.0
                        with self._lock:
                            self._append_log_locked(f"[任务{index}] 注册成功: {email or access_token[:12]}", "success")
                            self._config["stats"]["done"] = done
                            self._config["stats"]["success"] = success
                            self._config["stats"]["fail"] = fail
                            self._refresh_stats_locked()
                            self._save_locked()
                    except Exception as exc:
                        done += 1
                        fail += 1
                        consecutive_failures += 1
                        backoff_seconds = _failure_backoff_seconds(consecutive_failures)
                        pending_backoff_seconds = max(pending_backoff_seconds, backoff_seconds)
                        with self._lock:
                            self._append_log_locked(f"[任务{index}] 注册失败: {exc}", "danger")
                            if backoff_seconds > 0:
                                self._append_log_locked(
                                    f"连续失败 {consecutive_failures} 次，可能触发上游或临时邮箱限流；runner 将等待 {backoff_seconds:.0f} 秒后重试。",
                                    "warning",
                                )
                            self._config["stats"]["done"] = done
                            self._config["stats"]["success"] = success
                            self._config["stats"]["fail"] = fail
                            self._refresh_stats_locked()
                            self._save_locked()
        with self._lock:
            self._config["enabled"] = False
            self._refresh_stats_locked()
            self._config["stats"]["running"] = 0
            self._config["stats"]["finished_at"] = _now_text()
            self._save_locked()
            self._runner = None
            self._stop_event = None


register_service = RegisterService(REGISTER_FILE)
