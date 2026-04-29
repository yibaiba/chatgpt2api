import json
import tempfile
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
ROOT_CONFIG_FILE = ROOT_DIR / "config.json"


class ConfigLoadingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._created_root_config = False
        if not ROOT_CONFIG_FILE.exists():
            ROOT_CONFIG_FILE.write_text(json.dumps({"auth-key": "test-auth"}), encoding="utf-8")
            cls._created_root_config = True

        from services import config as config_module

        cls.config_module = config_module

    @classmethod
    def tearDownClass(cls) -> None:
        if cls._created_root_config and ROOT_CONFIG_FILE.exists():
            ROOT_CONFIG_FILE.unlink()

    def test_load_settings_ignores_directory_config_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            base_dir = Path(tmp_dir)
            data_dir = base_dir / "data"
            config_dir = base_dir / "config.json"
            os_auth_key = "env-auth"

            config_dir.mkdir()

            module = self.config_module
            old_base_dir = module.BASE_DIR
            old_data_dir = module.DATA_DIR
            old_config_file = module.CONFIG_FILE
            old_env_auth_key = module.os.environ.get("CHATGPT2API_AUTH_KEY")
            try:
                module.BASE_DIR = base_dir
                module.DATA_DIR = data_dir
                module.CONFIG_FILE = config_dir
                module.os.environ["CHATGPT2API_AUTH_KEY"] = os_auth_key

                settings = module._load_settings()

                self.assertEqual(settings.auth_key, os_auth_key)
                self.assertEqual(settings.refresh_account_interval_minute, 5)
                self.assertEqual(settings.remote_account_sync_interval_minute, 60)
            finally:
                module.BASE_DIR = old_base_dir
                module.DATA_DIR = old_data_dir
                module.CONFIG_FILE = old_config_file
                if old_env_auth_key is None:
                    module.os.environ.pop("CHATGPT2API_AUTH_KEY", None)
                else:
                    module.os.environ["CHATGPT2API_AUTH_KEY"] = old_env_auth_key

    def test_config_store_hashes_and_hides_admin_auth_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            base_dir = Path(tmp_dir)
            config_file = base_dir / "config.json"
            config_file.write_text(json.dumps({"auth-key": "plain-secret"}), encoding="utf-8")

            module = self.config_module
            old_env_auth_key = module.os.environ.get("CHATGPT2API_AUTH_KEY")
            try:
                module.os.environ.pop("CHATGPT2API_AUTH_KEY", None)
                store = module.ConfigStore(config_file)
                raw = json.loads(config_file.read_text(encoding="utf-8"))

                self.assertNotIn("auth-key", raw)
                self.assertIn("auth-key-hash", raw)
                self.assertTrue(store.verify_admin_auth_key("plain-secret"))
                self.assertEqual(store.get()["auth-key"], "")
                self.assertTrue(store.get()["auth_key_configured"])
            finally:
                if old_env_auth_key is None:
                    module.os.environ.pop("CHATGPT2API_AUTH_KEY", None)
                else:
                    module.os.environ["CHATGPT2API_AUTH_KEY"] = old_env_auth_key

    def test_config_store_normalizes_remote_sync_interval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            base_dir = Path(tmp_dir)
            config_file = base_dir / "config.json"
            config_file.write_text(
                json.dumps({"auth-key": "plain-secret", "remote_account_sync_interval_minute": 0}),
                encoding="utf-8",
            )

            module = self.config_module
            old_env_auth_key = module.os.environ.get("CHATGPT2API_AUTH_KEY")
            try:
                module.os.environ.pop("CHATGPT2API_AUTH_KEY", None)
                store = module.ConfigStore(config_file)

                self.assertEqual(1, store.remote_account_sync_interval_minute)

                data = store.update({"remote_account_sync_interval_minute": "15"})

                self.assertEqual(15, data["remote_account_sync_interval_minute"])
                self.assertEqual(15, store.remote_account_sync_interval_minute)
            finally:
                if old_env_auth_key is None:
                    module.os.environ.pop("CHATGPT2API_AUTH_KEY", None)
                else:
                    module.os.environ["CHATGPT2API_AUTH_KEY"] = old_env_auth_key

    def test_config_store_preserves_existing_auth_hash_when_blank_auth_key_is_submitted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            base_dir = Path(tmp_dir)
            config_file = base_dir / "config.json"
            config_file.write_text(json.dumps({"auth-key": "plain-secret"}), encoding="utf-8")

            module = self.config_module
            old_env_auth_key = module.os.environ.get("CHATGPT2API_AUTH_KEY")
            try:
                module.os.environ.pop("CHATGPT2API_AUTH_KEY", None)
                store = module.ConfigStore(config_file)
                original_hash = str(store.data.get("auth-key-hash") or "")

                data = store.update({"auth-key": "", "remote_account_sync_interval_minute": 60})
                raw = json.loads(config_file.read_text(encoding="utf-8"))

                self.assertEqual("", data["auth-key"])
                self.assertEqual(original_hash, raw.get("auth-key-hash"))
                self.assertTrue(store.verify_admin_auth_key("plain-secret"))
            finally:
                if old_env_auth_key is None:
                    module.os.environ.pop("CHATGPT2API_AUTH_KEY", None)
                else:
                    module.os.environ["CHATGPT2API_AUTH_KEY"] = old_env_auth_key

    def test_config_store_normalizes_sensitive_words(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            base_dir = Path(tmp_dir)
            config_file = base_dir / "config.json"
            config_file.write_text(json.dumps({"auth-key": "plain-secret"}), encoding="utf-8")

            module = self.config_module
            old_env_auth_key = module.os.environ.get("CHATGPT2API_AUTH_KEY")
            try:
                module.os.environ.pop("CHATGPT2API_AUTH_KEY", None)
                store = module.ConfigStore(config_file)

                data = store.update(
                    {
                        "sensitive_word_filter_enabled": "true",
                        "sensitive_words": ["  NSFW  ", "", "nsfw", "Violence"],
                    }
                )

                self.assertTrue(data["sensitive_word_filter_enabled"])
                self.assertEqual(["NSFW", "Violence"], data["sensitive_words"])
                self.assertEqual(["NSFW", "Violence"], store.sensitive_words)
            finally:
                if old_env_auth_key is None:
                    module.os.environ.pop("CHATGPT2API_AUTH_KEY", None)
                else:
                    module.os.environ["CHATGPT2API_AUTH_KEY"] = old_env_auth_key

    def test_config_store_normalizes_storage_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            base_dir = Path(tmp_dir)
            sqlite_path = base_dir / "custom.sqlite3"
            config_file = base_dir / "config.json"
            config_file.write_text(json.dumps({"auth-key": "plain-secret"}), encoding="utf-8")

            module = self.config_module
            old_env_auth_key = module.os.environ.get("CHATGPT2API_AUTH_KEY")
            try:
                module.os.environ.pop("CHATGPT2API_AUTH_KEY", None)
                store = module.ConfigStore(config_file)

                data = store.update(
                    {
                        "storage_backend": "SQLITE",
                        "storage_sqlite_path": f"  {sqlite_path}  ",
                    }
                )

                self.assertEqual("sqlite", data["storage_backend"])
                self.assertEqual(str(sqlite_path), data["storage_sqlite_path"])
                self.assertEqual("sqlite", store.storage_backend)
                self.assertEqual(sqlite_path, store.storage_sqlite_path)
            finally:
                if old_env_auth_key is None:
                    module.os.environ.pop("CHATGPT2API_AUTH_KEY", None)
                else:
                    module.os.environ["CHATGPT2API_AUTH_KEY"] = old_env_auth_key

    def test_config_store_rejects_unsupported_storage_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            base_dir = Path(tmp_dir)
            config_file = base_dir / "config.json"
            config_file.write_text(json.dumps({"auth-key": "plain-secret"}), encoding="utf-8")

            module = self.config_module
            old_env_auth_key = module.os.environ.get("CHATGPT2API_AUTH_KEY")
            try:
                module.os.environ.pop("CHATGPT2API_AUTH_KEY", None)
                store = module.ConfigStore(config_file)

                with self.assertRaisesRegex(ValueError, "unsupported storage_backend: postgres"):
                    store.update({"storage_backend": "postgres"})
            finally:
                if old_env_auth_key is None:
                    module.os.environ.pop("CHATGPT2API_AUTH_KEY", None)
                else:
                    module.os.environ["CHATGPT2API_AUTH_KEY"] = old_env_auth_key

    def test_config_store_public_storage_settings_follow_env_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            base_dir = Path(tmp_dir)
            sqlite_path = base_dir / "env.sqlite3"
            config_file = base_dir / "config.json"
            config_file.write_text(
                json.dumps(
                    {
                        "auth-key": "plain-secret",
                        "storage_backend": "sqlite",
                        "storage_sqlite_path": str(base_dir / "configured.sqlite3"),
                    }
                ),
                encoding="utf-8",
            )

            module = self.config_module
            old_env_auth_key = module.os.environ.get("CHATGPT2API_AUTH_KEY")
            old_env_backend = module.os.environ.get("CHATGPT2API_STORAGE_BACKEND")
            old_env_sqlite = module.os.environ.get("CHATGPT2API_STORAGE_SQLITE_PATH")
            try:
                module.os.environ.pop("CHATGPT2API_AUTH_KEY", None)
                module.os.environ["CHATGPT2API_STORAGE_BACKEND"] = "json"
                module.os.environ["CHATGPT2API_STORAGE_SQLITE_PATH"] = str(sqlite_path)
                store = module.ConfigStore(config_file)

                public = store.get()

                self.assertEqual("json", public["storage_backend"])
                self.assertEqual(str(sqlite_path), public["storage_sqlite_path"])
                self.assertTrue(public["storage_env_override_active"])
                self.assertEqual(
                    ["CHATGPT2API_STORAGE_BACKEND", "CHATGPT2API_STORAGE_SQLITE_PATH"],
                    store.active_storage_override_env_vars(),
                )
            finally:
                if old_env_auth_key is None:
                    module.os.environ.pop("CHATGPT2API_AUTH_KEY", None)
                else:
                    module.os.environ["CHATGPT2API_AUTH_KEY"] = old_env_auth_key
                if old_env_backend is None:
                    module.os.environ.pop("CHATGPT2API_STORAGE_BACKEND", None)
                else:
                    module.os.environ["CHATGPT2API_STORAGE_BACKEND"] = old_env_backend
                if old_env_sqlite is None:
                    module.os.environ.pop("CHATGPT2API_STORAGE_SQLITE_PATH", None)
                else:
                    module.os.environ["CHATGPT2API_STORAGE_SQLITE_PATH"] = old_env_sqlite

    def test_config_store_hashes_and_hides_admin_auth_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            base_dir = Path(tmp_dir)
            config_file = base_dir / "config.json"
            config_file.write_text(json.dumps({"auth-key": "plain-secret"}), encoding="utf-8")

            module = self.config_module
            old_env_auth_key = module.os.environ.get("CHATGPT2API_AUTH_KEY")
            try:
                module.os.environ.pop("CHATGPT2API_AUTH_KEY", None)
                store = module.ConfigStore(config_file)
                raw = json.loads(config_file.read_text(encoding="utf-8"))

                self.assertNotIn("auth-key", raw)
                self.assertIn("auth-key-hash", raw)
                self.assertTrue(store.verify_admin_auth_key("plain-secret"))
                self.assertEqual(store.get()["auth-key"], "")
                self.assertTrue(store.get()["auth_key_configured"])
            finally:
                if old_env_auth_key is None:
                    module.os.environ.pop("CHATGPT2API_AUTH_KEY", None)
                else:
                    module.os.environ["CHATGPT2API_AUTH_KEY"] = old_env_auth_key


if __name__ == "__main__":
    unittest.main()
