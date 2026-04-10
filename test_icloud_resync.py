"""Comprehensive tests for icloud_resync.py."""

import json
import os
import time
import types
from unittest import mock

import pytest

import icloud_resync

# ── Shared Tk fixture ─────────────────────────────────────────
# tkinter widgets (StringVar, Text, etc.) require a real Tk root.
# We create one hidden root per test that needs it.


@pytest.fixture(scope="module")
def _tk_root_shared():
    """Single hidden Tk root for the entire test module (avoids Tk lifecycle issues)."""
    import tkinter as tk
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip("No display available for Tk tests")
    yield root
    root.destroy()


@pytest.fixture
def tk_root(_tk_root_shared):
    """Per-test access to the shared Tk root."""
    return _tk_root_shared


@pytest.fixture
def app(tk_root):
    """Instantiate TouchApp with DnD disabled on a real Tk root."""
    with mock.patch.object(icloud_resync, "HAS_WINDND", False), \
         mock.patch.object(icloud_resync, "HAS_TKDND", False):
        return icloud_resync.TouchApp(tk_root)


# ── _parse_version ────────────────────────────────────────────

class TestParseVersion:
    def test_simple(self):
        assert icloud_resync._parse_version("1.2.3") == (1, 2, 3)

    def test_with_v_prefix(self):
        assert icloud_resync._parse_version("v1.2.3") == (1, 2, 3)

    def test_two_part(self):
        assert icloud_resync._parse_version("v2.0") == (2, 0)

    def test_single_part(self):
        assert icloud_resync._parse_version("5") == (5,)

    def test_comparison_ordering(self):
        assert icloud_resync._parse_version("v1.0.0") < icloud_resync._parse_version("v1.0.1")
        assert icloud_resync._parse_version("v1.9.9") < icloud_resync._parse_version("v2.0.0")
        assert icloud_resync._parse_version("v2.0.0") == icloud_resync._parse_version("2.0.0")

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            icloud_resync._parse_version("vABC")


# ── _asset_name ───────────────────────────────────────────────

class TestAssetName:
    def test_windows(self):
        with mock.patch.object(icloud_resync.sys, "platform", "win32"):
            assert icloud_resync._asset_name() == "iCloud_ReSyncTool.exe"

    def test_macos(self):
        with mock.patch.object(icloud_resync.sys, "platform", "darwin"):
            assert icloud_resync._asset_name() == "iCloud_ReSyncTool-macos"

    def test_linux(self):
        with mock.patch.object(icloud_resync.sys, "platform", "linux"):
            assert icloud_resync._asset_name() == "iCloud_ReSyncTool-linux"


# ── _check_for_update ────────────────────────────────────────

def _fake_release_json(tag, assets=None):
    """Build a GitHub-release-style JSON response."""
    if assets is None:
        assets = [
            {"name": "iCloud_ReSyncTool.exe", "browser_download_url": "https://example.com/win"},
            {"name": "iCloud_ReSyncTool-macos", "browser_download_url": "https://example.com/mac"},
            {"name": "iCloud_ReSyncTool-linux", "browser_download_url": "https://example.com/linux"},
        ]
    return json.dumps({"tag_name": tag, "assets": assets}).encode()


class TestCheckForUpdate:
    def _mock_urlopen(self, body_bytes):
        resp = mock.MagicMock()
        resp.read.return_value = body_bytes
        resp.__enter__ = mock.Mock(return_value=resp)
        resp.__exit__ = mock.Mock(return_value=False)
        return mock.patch("icloud_resync.urllib.request.urlopen", return_value=resp)

    def test_newer_version_available(self):
        with mock.patch.object(icloud_resync, "VERSION", "1.0.0"), \
             mock.patch.object(icloud_resync.sys, "platform", "win32"), \
             self._mock_urlopen(_fake_release_json("v2.0.0")):
            result = icloud_resync._check_for_update()
            assert result == ("v2.0.0", "https://example.com/win")

    def test_same_version_returns_none(self):
        with mock.patch.object(icloud_resync, "VERSION", "2.0.0"), \
             self._mock_urlopen(_fake_release_json("v2.0.0")):
            assert icloud_resync._check_for_update() is None

    def test_older_version_returns_none(self):
        with mock.patch.object(icloud_resync, "VERSION", "3.0.0"), \
             self._mock_urlopen(_fake_release_json("v2.0.0")):
            assert icloud_resync._check_for_update() is None

    def test_network_error_returns_none(self):
        with mock.patch("icloud_resync.urllib.request.urlopen", side_effect=OSError("no net")):
            assert icloud_resync._check_for_update() is None

    def test_missing_asset_returns_none(self):
        body = json.dumps({"tag_name": "v9.0.0", "assets": []}).encode()
        with mock.patch.object(icloud_resync, "VERSION", "1.0.0"), \
             self._mock_urlopen(body):
            assert icloud_resync._check_for_update() is None

    def test_empty_tag_returns_none(self):
        body = json.dumps({"tag_name": "", "assets": []}).encode()
        with self._mock_urlopen(body):
            assert icloud_resync._check_for_update() is None

    def test_invalid_tag_returns_none(self):
        body = json.dumps({"tag_name": "latest", "assets": []}).encode()
        with mock.patch.object(icloud_resync, "VERSION", "1.0.0"), \
             self._mock_urlopen(body):
            assert icloud_resync._check_for_update() is None

    def test_selects_correct_platform_asset(self):
        with mock.patch.object(icloud_resync, "VERSION", "1.0.0"), \
             mock.patch.object(icloud_resync.sys, "platform", "darwin"), \
             self._mock_urlopen(_fake_release_json("v2.0.0")):
            result = icloud_resync._check_for_update()
            assert result == ("v2.0.0", "https://example.com/mac")


# ── _apply_update ─────────────────────────────────────────────

class TestApplyUpdate:
    def test_not_frozen_reports_error(self):
        results = []
        with mock.patch.object(icloud_resync.sys, "frozen", False, create=True):
            icloud_resync._apply_update(
                "https://example.com/bin",
                done_cb=lambda ok, err: results.append((ok, err)),
            )
        assert results == [(False, "Cannot self-update when running from source.")]

    def test_downloads_and_replaces_unix(self, tmp_path):
        fake_exe = tmp_path / "app"
        fake_exe.write_bytes(b"old binary")
        fake_exe.chmod(0o755)

        new_binary = b"new binary content"
        resp = mock.MagicMock()
        resp.headers = {"Content-Length": str(len(new_binary))}
        resp.read = mock.Mock(side_effect=[new_binary, b""])
        resp.__enter__ = mock.Mock(return_value=resp)
        resp.__exit__ = mock.Mock(return_value=False)

        results = []
        progress_calls = []

        with mock.patch("icloud_resync.sys") as mock_sys, \
             mock.patch("icloud_resync.urllib.request.urlopen", return_value=resp):
            mock_sys.platform = "linux"
            mock_sys.executable = str(fake_exe)
            type(mock_sys).frozen = mock.PropertyMock(return_value=True)

            icloud_resync._apply_update(
                "https://example.com/bin",
                progress_cb=lambda d, t: progress_calls.append((d, t)),
                done_cb=lambda ok, err: results.append((ok, err)),
            )

        assert results == [(True, None)]
        assert fake_exe.read_bytes() == new_binary
        assert len(progress_calls) > 0

    def test_downloads_and_replaces_windows(self, tmp_path):
        fake_exe = tmp_path / "app.exe"
        fake_exe.write_bytes(b"old binary")

        new_binary = b"new binary content"
        resp = mock.MagicMock()
        resp.headers = {"Content-Length": str(len(new_binary))}
        resp.read = mock.Mock(side_effect=[new_binary, b""])
        resp.__enter__ = mock.Mock(return_value=resp)
        resp.__exit__ = mock.Mock(return_value=False)

        results = []

        with mock.patch("icloud_resync.sys") as mock_sys, \
             mock.patch("icloud_resync.urllib.request.urlopen", return_value=resp):
            mock_sys.platform = "win32"
            mock_sys.executable = str(fake_exe)
            type(mock_sys).frozen = mock.PropertyMock(return_value=True)

            icloud_resync._apply_update(
                "https://example.com/bin",
                done_cb=lambda ok, err: results.append((ok, err)),
            )

        assert results == [(True, None)]
        assert fake_exe.read_bytes() == new_binary
        assert (tmp_path / "app.exe.old").exists()

    def test_download_error_calls_done_with_failure(self):
        results = []
        with mock.patch("icloud_resync.sys") as mock_sys, \
             mock.patch("icloud_resync.urllib.request.urlopen", side_effect=OSError("fail")):
            mock_sys.executable = "/fake/app"
            type(mock_sys).frozen = mock.PropertyMock(return_value=True)

            icloud_resync._apply_update(
                "https://example.com/bin",
                done_cb=lambda ok, err: results.append((ok, err)),
            )

        assert len(results) == 1
        assert results[0][0] is False
        assert "fail" in results[0][1]


# ── TouchApp._set_dropped_path ────────────────────────────────

class TestSetDroppedPath:
    def test_directory_sets_var(self, app, tmp_path):
        assert app._set_dropped_path(str(tmp_path)) is True
        assert app.folder_var.get() == str(tmp_path)

    def test_file_resolves_to_parent(self, app, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello")
        assert app._set_dropped_path(str(f)) is True
        assert app.folder_var.get() == str(tmp_path)

    def test_nonexistent_returns_false(self, app):
        assert app._set_dropped_path("/nonexistent/path/xyz") is False


# ── Drag-and-drop handlers ───────────────────────────────────

class TestOnDropWindnd:
    def test_bytes_paths(self, app, tmp_path):
        app._on_drop_windnd([str(tmp_path).encode("utf-8")])
        assert app.folder_var.get() == str(tmp_path)

    def test_string_paths(self, app, tmp_path):
        app._on_drop_windnd([str(tmp_path)])
        assert app.folder_var.get() == str(tmp_path)

    def test_picks_first_valid(self, app, tmp_path):
        app._on_drop_windnd([b"/nonexistent", str(tmp_path).encode()])
        assert app.folder_var.get() == str(tmp_path)

    def test_empty_list(self, app):
        app._on_drop_windnd([])
        assert app.folder_var.get() == ""


class TestOnDropTkdnd:
    def test_simple_path(self, app, tmp_path):
        event = types.SimpleNamespace(data=str(tmp_path))
        app._on_drop_tkdnd(event)
        assert app.folder_var.get() == str(tmp_path)

    def test_braced_path_with_spaces(self, app, tmp_path):
        event = types.SimpleNamespace(data="{" + str(tmp_path) + "}")
        app._on_drop_tkdnd(event)
        assert app.folder_var.get() == str(tmp_path)

    def test_multiple_braced_paths(self, app, tmp_path):
        sub1 = tmp_path / "a"
        sub2 = tmp_path / "b"
        sub1.mkdir()
        sub2.mkdir()
        event = types.SimpleNamespace(data="{" + str(sub1) + "} {" + str(sub2) + "}")
        app._on_drop_tkdnd(event)
        assert app.folder_var.get() == str(sub1)

    def test_file_in_braces(self, app, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("hi")
        event = types.SimpleNamespace(data="{" + str(f) + "}")
        app._on_drop_tkdnd(event)
        assert app.folder_var.get() == str(tmp_path)


# ── touch_files logic ─────────────────────────────────────────

class TestTouchFiles:
    def _run_touch(self, app, folder, recursive=True, hidden=False):
        """Run touch_files synchronously (it's normally threaded)."""
        app.recursive_var.set(recursive)
        app.hidden_var.set(hidden)
        # Replace root.after so callbacks run immediately in-line
        app.root.after = lambda _ms, fn, *a, **kw: fn(*a, **kw)
        app.touch_files(str(folder))

    def test_touches_files_and_updates_mtime(self, app, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("hello")
        old_time = time.time() - 3600
        os.utime(f, (old_time, old_time))

        self._run_touch(app, tmp_path)
        assert os.path.getmtime(f) > old_time

    def test_recursive_touches_subfolders(self, app, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        f = sub / "deep.txt"
        f.write_text("deep")
        old_time = time.time() - 3600
        os.utime(f, (old_time, old_time))

        self._run_touch(app, tmp_path, recursive=True)
        assert os.path.getmtime(f) > old_time

    def test_non_recursive_skips_subfolders(self, app, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        f = sub / "deep.txt"
        f.write_text("deep")
        old_time = time.time() - 3600
        os.utime(f, (old_time, old_time))

        self._run_touch(app, tmp_path, recursive=False)
        assert os.path.getmtime(f) == pytest.approx(old_time, abs=1)

    def test_hidden_files_skipped_by_default(self, app, tmp_path):
        visible = tmp_path / "visible.txt"
        hidden = tmp_path / ".hidden"
        visible.write_text("v")
        hidden.write_text("h")
        old_time = time.time() - 3600
        os.utime(hidden, (old_time, old_time))

        self._run_touch(app, tmp_path, hidden=False)
        assert os.path.getmtime(hidden) == pytest.approx(old_time, abs=1)
        assert os.path.getmtime(visible) > old_time

    def test_hidden_files_included_when_enabled(self, app, tmp_path):
        hidden = tmp_path / ".hidden"
        hidden.write_text("h")
        old_time = time.time() - 3600
        os.utime(hidden, (old_time, old_time))

        self._run_touch(app, tmp_path, hidden=True)
        assert os.path.getmtime(hidden) > old_time

    def test_hidden_dirs_skipped_by_default(self, app, tmp_path):
        hidden_dir = tmp_path / ".secret"
        hidden_dir.mkdir()
        f = hidden_dir / "file.txt"
        f.write_text("x")
        old_time = time.time() - 3600
        os.utime(f, (old_time, old_time))

        self._run_touch(app, tmp_path, recursive=True, hidden=False)
        assert os.path.getmtime(f) == pytest.approx(old_time, abs=1)

    def test_hidden_dirs_included_when_enabled(self, app, tmp_path):
        hidden_dir = tmp_path / ".secret"
        hidden_dir.mkdir()
        f = hidden_dir / "file.txt"
        f.write_text("x")
        old_time = time.time() - 3600
        os.utime(f, (old_time, old_time))

        self._run_touch(app, tmp_path, recursive=True, hidden=True)
        assert os.path.getmtime(f) > old_time

    def test_permission_error_logged(self, app, tmp_path):
        f = tmp_path / "locked.txt"
        f.write_text("x")

        logged_errors = []

        def capture_log(msg, error=False):
            if error:
                logged_errors.append(msg)

        app.log_msg = capture_log
        app.root.after = lambda _ms, fn, *a, **kw: fn(*a, **kw)
        app.recursive_var.set(True)
        app.hidden_var.set(False)

        with mock.patch("os.utime", side_effect=PermissionError("denied")):
            app.touch_files(str(tmp_path))

        assert len(logged_errors) == 1
        assert "ERR" in logged_errors[0]

    def test_empty_directory(self, app, tmp_path):
        """Touching an empty folder completes without error."""
        app.root.after = lambda _ms, fn, *a, **kw: fn(*a, **kw)
        app.recursive_var.set(True)
        app.hidden_var.set(False)
        app.touch_files(str(tmp_path))
        assert app.status_var.get().startswith("Done.")

    def test_multiple_files(self, app, tmp_path):
        """All files in directory get touched."""
        files = []
        for name in ("a.txt", "b.txt", "c.txt"):
            f = tmp_path / name
            f.write_text(name)
            old_time = time.time() - 3600
            os.utime(f, (old_time, old_time))
            files.append(f)

        self._run_touch(app, tmp_path)

        for f in files:
            assert os.path.getmtime(f) > time.time() - 10


# ── finish ────────────────────────────────────────────────────

class TestFinish:
    def test_resets_state(self, app):
        app.running = True
        app.finish("Done.")
        assert app.running is False
        assert app.status_var.get() == "Done."


# ── log_msg with real Tk widgets ──────────────────────────────

class TestLogMsg:
    def test_normal_message_no_tag(self, app):
        app.log_msg("info line")
        content = app.log.get("1.0", "end").strip()
        assert content == "info line"
        tags = app.log.tag_ranges("error")
        assert len(tags) == 0

    def test_error_message_has_tag(self, app):
        app.log_msg("bad thing", error=True)
        tags = app.log.tag_ranges("error")
        assert len(tags) > 0

    def test_mixed_messages(self, app):
        app.log_msg("ok")
        app.log_msg("fail", error=True)
        app.log_msg("ok2")
        content = app.log.get("1.0", "end").strip()
        assert "ok" in content
        assert "fail" in content
        assert "ok2" in content
        # One tagged region = 2 indices (start + end)
        tags = app.log.tag_ranges("error")
        assert len(tags) == 2


# ── browse ────────────────────────────────────────────────────

class TestBrowse:
    def test_browse_sets_path(self, app, tmp_path):
        with mock.patch("icloud_resync.filedialog.askdirectory", return_value=str(tmp_path)):
            app.browse()
        assert app.folder_var.get() == str(tmp_path)

    def test_browse_cancelled(self, app):
        with mock.patch("icloud_resync.filedialog.askdirectory", return_value=""):
            app.browse()
        assert app.folder_var.get() == ""


# ── start ─────────────────────────────────────────────────────

class TestStart:
    def test_rejects_empty(self, app):
        app.folder_var.set("")
        with mock.patch("icloud_resync.messagebox.showwarning") as warn:
            app.start()
        warn.assert_called_once()
        assert app.running is False

    def test_rejects_invalid_path(self, app):
        app.folder_var.set("/nonexistent/path/xyz")
        with mock.patch("icloud_resync.messagebox.showwarning") as warn:
            app.start()
        warn.assert_called_once()
        assert app.running is False

    def test_ignores_if_running(self, app, tmp_path):
        app.folder_var.set(str(tmp_path))
        app.running = True
        with mock.patch("icloud_resync.threading.Thread") as thread_cls:
            app.start()
        thread_cls.assert_not_called()

    def test_launches_thread(self, app, tmp_path):
        app.folder_var.set(str(tmp_path))
        with mock.patch("icloud_resync.threading.Thread") as thread_cls:
            thread_cls.return_value = mock.MagicMock()
            app.start()
        thread_cls.assert_called_once()
        assert app.running is True


# ── VERSION / GITHUB_REPO constants ──────────────────────────

class TestConstants:
    def test_version_format(self):
        parts = icloud_resync.VERSION.split(".")
        assert len(parts) == 3
        for p in parts:
            int(p)  # each part must be numeric

    def test_github_repo_format(self):
        assert "/" in icloud_resync.GITHUB_REPO
        owner, repo = icloud_resync.GITHUB_REPO.split("/")
        assert len(owner) > 0
        assert len(repo) > 0
