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
# We create one hidden root shared across the module.


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
        a = icloud_resync.TouchApp(tk_root)
    yield a
    # Clean up for next test
    a.clear_targets()


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


# ── add_target / remove / clear ──────────────────────────────

class TestTargetManagement:
    def test_add_folder(self, app, tmp_path):
        assert app.add_target(str(tmp_path)) is True
        assert len(app.targets) == 1
        assert app.target_listbox.size() == 1

    def test_add_file(self, app, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello")
        assert app.add_target(str(f)) is True
        assert len(app.targets) == 1

    def test_no_duplicates(self, app, tmp_path):
        app.add_target(str(tmp_path))
        app.add_target(str(tmp_path))
        assert len(app.targets) == 1

    def test_nonexistent_rejected(self, app):
        assert app.add_target("/nonexistent/path/xyz") is False
        assert len(app.targets) == 0

    def test_remove_selected(self, app, tmp_path):
        sub1 = tmp_path / "a"
        sub2 = tmp_path / "b"
        sub1.mkdir()
        sub2.mkdir()
        app.add_target(str(sub1))
        app.add_target(str(sub2))
        app.target_listbox.selection_set(0)
        app.remove_selected()
        assert len(app.targets) == 1
        assert os.path.normpath(str(sub2)) in app.targets[0]

    def test_clear_targets(self, app, tmp_path):
        app.add_target(str(tmp_path))
        app.clear_targets()
        assert len(app.targets) == 0
        assert app.target_listbox.size() == 0


# ── Drag-and-drop handlers ───────────────────────────────────

class TestOnDropWindnd:
    def test_adds_all_dropped_paths(self, app, tmp_path):
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("a")
        f2.write_text("b")
        app._on_drop_windnd([str(f1).encode(), str(f2).encode()])
        assert len(app.targets) == 2

    def test_bytes_paths(self, app, tmp_path):
        app._on_drop_windnd([str(tmp_path).encode("utf-8")])
        assert len(app.targets) == 1

    def test_string_paths(self, app, tmp_path):
        app._on_drop_windnd([str(tmp_path)])
        assert len(app.targets) == 1

    def test_skips_invalid(self, app, tmp_path):
        app._on_drop_windnd([b"/nonexistent", str(tmp_path).encode()])
        assert len(app.targets) == 1

    def test_empty_list(self, app):
        app._on_drop_windnd([])
        assert len(app.targets) == 0


class TestOnDropTkdnd:
    def test_simple_path(self, app, tmp_path):
        event = types.SimpleNamespace(data=str(tmp_path))
        app._on_drop_tkdnd(event)
        assert len(app.targets) == 1

    def test_braced_path(self, app, tmp_path):
        event = types.SimpleNamespace(data="{" + str(tmp_path) + "}")
        app._on_drop_tkdnd(event)
        assert len(app.targets) == 1

    def test_multiple_braced_paths(self, app, tmp_path):
        sub1 = tmp_path / "a"
        sub2 = tmp_path / "b"
        sub1.mkdir()
        sub2.mkdir()
        event = types.SimpleNamespace(data="{" + str(sub1) + "} {" + str(sub2) + "}")
        app._on_drop_tkdnd(event)
        assert len(app.targets) == 2

    def test_file_added_directly(self, app, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("hi")
        event = types.SimpleNamespace(data="{" + str(f) + "}")
        app._on_drop_tkdnd(event)
        assert len(app.targets) == 1
        assert os.path.normpath(str(f)) in app.targets[0]


# ── touch_files logic ─────────────────────────────────────────

class TestTouchFiles:
    def _run_touch(self, app, targets, recursive=True, hidden=False):
        """Run touch_files synchronously with a list of targets."""
        app.recursive_var.set(recursive)
        app.hidden_var.set(hidden)
        app.root.after = lambda _ms, fn, *a, **kw: fn(*a, **kw)
        if isinstance(targets, list):
            app.touch_files([str(t) for t in targets])
        else:
            app.touch_files([str(targets)])

    def test_touches_files_in_folder(self, app, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("hello")
        old_time = time.time() - 3600
        os.utime(f, (old_time, old_time))

        self._run_touch(app, tmp_path)
        assert os.path.getmtime(f) > old_time

    def test_touches_individual_file(self, app, tmp_path):
        f = tmp_path / "single.txt"
        f.write_text("data")
        old_time = time.time() - 3600
        os.utime(f, (old_time, old_time))

        self._run_touch(app, f)
        assert os.path.getmtime(f) > old_time

    def test_mixed_files_and_folders(self, app, tmp_path):
        """Touch a mix of individual files and folders."""
        folder = tmp_path / "dir"
        folder.mkdir()
        f_in_folder = folder / "inside.txt"
        f_in_folder.write_text("x")
        standalone = tmp_path / "standalone.txt"
        standalone.write_text("y")

        old_time = time.time() - 3600
        os.utime(f_in_folder, (old_time, old_time))
        os.utime(standalone, (old_time, old_time))

        self._run_touch(app, [standalone, folder])

        assert os.path.getmtime(f_in_folder) > old_time
        assert os.path.getmtime(standalone) > old_time

    def test_files_from_different_directories(self, app, tmp_path):
        """Files from different directories can all be touched."""
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()
        f1 = dir_a / "f1.txt"
        f2 = dir_b / "f2.txt"
        f1.write_text("1")
        f2.write_text("2")

        old_time = time.time() - 3600
        os.utime(f1, (old_time, old_time))
        os.utime(f2, (old_time, old_time))

        self._run_touch(app, [f1, f2])

        assert os.path.getmtime(f1) > old_time
        assert os.path.getmtime(f2) > old_time

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

    def test_hidden_individual_file_skipped_by_default(self, app, tmp_path):
        hidden = tmp_path / ".hidden"
        hidden.write_text("h")
        old_time = time.time() - 3600
        os.utime(hidden, (old_time, old_time))

        self._run_touch(app, hidden, hidden=False)
        assert os.path.getmtime(hidden) == pytest.approx(old_time, abs=1)

    def test_hidden_individual_file_included_when_enabled(self, app, tmp_path):
        hidden = tmp_path / ".hidden"
        hidden.write_text("h")
        old_time = time.time() - 3600
        os.utime(hidden, (old_time, old_time))

        self._run_touch(app, hidden, hidden=True)
        assert os.path.getmtime(hidden) > old_time

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
            app.touch_files([str(tmp_path)])

        assert len(logged_errors) == 1
        assert "ERR" in logged_errors[0]

    def test_empty_directory(self, app, tmp_path):
        app.root.after = lambda _ms, fn, *a, **kw: fn(*a, **kw)
        app.recursive_var.set(True)
        app.hidden_var.set(False)
        app.touch_files([str(tmp_path)])
        assert app.status_var.get().startswith("Done.")

    def test_multiple_files_in_folder(self, app, tmp_path):
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
        assert "info line" in content
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


# ── browse ────────────────────────────────────────────────────

class TestBrowse:
    def test_browse_folder_adds_target(self, app, tmp_path):
        with mock.patch("icloud_resync.filedialog.askdirectory", return_value=str(tmp_path)):
            app.browse_folder()
        assert len(app.targets) == 1

    def test_browse_folder_cancelled(self, app):
        with mock.patch("icloud_resync.filedialog.askdirectory", return_value=""):
            app.browse_folder()
        assert len(app.targets) == 0

    def test_browse_files_adds_targets(self, app, tmp_path):
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("a")
        f2.write_text("b")
        with mock.patch("icloud_resync.filedialog.askopenfilenames",
                        return_value=(str(f1), str(f2))):
            app.browse_files()
        assert len(app.targets) == 2

    def test_browse_files_cancelled(self, app):
        with mock.patch("icloud_resync.filedialog.askopenfilenames", return_value=()):
            app.browse_files()
        assert len(app.targets) == 0


# ── start ─────────────────────────────────────────────────────

class TestStart:
    def test_rejects_empty_targets(self, app):
        with mock.patch("icloud_resync.messagebox.showwarning") as warn:
            app.start()
        warn.assert_called_once()
        assert app.running is False

    def test_ignores_if_running(self, app, tmp_path):
        app.add_target(str(tmp_path))
        app.running = True
        with mock.patch("icloud_resync.threading.Thread") as thread_cls:
            app.start()
        thread_cls.assert_not_called()

    def test_launches_thread(self, app, tmp_path):
        app.add_target(str(tmp_path))
        with mock.patch("icloud_resync.threading.Thread") as thread_cls:
            thread_cls.return_value = mock.MagicMock()
            app.start()
        thread_cls.assert_called_once()
        assert app.running is True


# ── iCloud restart helpers ────────────────────────────────────

class TestKillICloudProcesses:
    def test_kills_running_processes(self):
        with mock.patch.object(icloud_resync.sys, "platform", "win32"), \
             mock.patch("icloud_resync._get_running_icloud_processes",
                        return_value={"iCloud.exe", "iCloudHome.exe"}), \
             mock.patch("icloud_resync.subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(returncode=0)
            killed = icloud_resync._kill_icloud_processes()
        assert "iCloud.exe" in killed
        assert "iCloudHome.exe" in killed
        assert len(killed) == 2

    def test_returns_empty_when_none_running(self):
        with mock.patch.object(icloud_resync.sys, "platform", "win32"), \
             mock.patch("icloud_resync._get_running_icloud_processes", return_value=set()):
            killed = icloud_resync._kill_icloud_processes()
        assert killed == []

    def test_returns_empty_on_non_windows(self):
        with mock.patch.object(icloud_resync.sys, "platform", "linux"):
            assert icloud_resync._kill_icloud_processes() == []

    def test_get_running_detects_icloud_processes(self):
        fake_output = (
            '"iCloud.exe","1234","Console","1","98,000 K"\n'
            '"iCloudHome.exe","5678","Console","1","85,000 K"\n'
            '"iCloud_ReSyncTool.exe","4321","Console","1","18,000 K"\n'
            '"explorer.exe","9999","Console","1","50,000 K"\n'
        )
        with mock.patch.object(icloud_resync.sys, "platform", "win32"), \
             mock.patch("icloud_resync.subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(returncode=0, stdout=fake_output)
            running = icloud_resync._get_running_icloud_processes()
        assert "iCloud.exe" in running
        assert "iCloudHome.exe" in running
        assert "explorer.exe" not in running
        assert "iCloud_ReSyncTool.exe" not in running  # must not kill ourselves


class TestFindICloudExe:
    def test_finds_desktop_install(self, tmp_path):
        fake_exe = tmp_path / "iCloud.exe"
        fake_exe.write_text("exe")
        with mock.patch.object(icloud_resync.sys, "platform", "win32"), \
             mock.patch("os.path.expandvars", return_value=str(fake_exe)):
            result = icloud_resync._find_icloud_exe()
        assert result == str(fake_exe)

    def test_returns_none_on_non_windows(self):
        with mock.patch.object(icloud_resync.sys, "platform", "linux"):
            assert icloud_resync._find_icloud_exe() is None

    def test_returns_none_when_not_installed(self):
        with mock.patch.object(icloud_resync.sys, "platform", "win32"), \
             mock.patch("os.path.expandvars", return_value="/nonexistent/iCloud.exe"), \
             mock.patch("os.path.isdir", return_value=False), \
             mock.patch("icloud_resync.subprocess.run",
                        return_value=mock.MagicMock(returncode=1)):
            assert icloud_resync._find_icloud_exe() is None


class TestRestartICloud:
    def test_ignores_if_running(self, app):
        app.running = True
        with mock.patch("icloud_resync.threading.Thread") as thread_cls:
            app.restart_icloud()
        thread_cls.assert_not_called()

    def test_launches_thread(self, app):
        with mock.patch("icloud_resync.threading.Thread") as thread_cls:
            thread_cls.return_value = mock.MagicMock()
            app.restart_icloud()
        thread_cls.assert_called_once()
        assert app.running is True

    def test_finish_restart_resets_state(self, app):
        app.running = True
        app._finish_restart("iCloud restarted.")
        assert app.running is False
        assert app.status_var.get() == "iCloud restarted."


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
