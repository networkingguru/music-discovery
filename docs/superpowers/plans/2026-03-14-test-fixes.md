# Test Fixes Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 4 broken tests in `tests/test_music_discovery.py` by replacing blanket mocks with stateful mocks that match actual call sequences.

**Architecture:** Each test's blanket `_run_applescript` mock is replaced with an iterator-based mock that returns the correct value for each call in the production code's sequence. For `_get_machine_seed`, the single broken test is replaced with three platform-specific tests.

**Tech Stack:** Python, pytest, monkeypatch, unittest.mock (patch, MagicMock)

**Spec:** `docs/superpowers/specs/2026-03-14-test-fixes-design.md`

---

## Chunk 1: All Test Fixes

### Task 1: Fix `test_setup_playlist_returns_true_on_success`

**Files:**
- Modify: `tests/test_music_discovery.py:684-687`

**Context:** `setup_playlist()` (in `music_discovery.py:667`) calls `_run_applescript` multiple times:
1. Count query — expects output parseable as `int`
2. Create/delete/clear — depends on count value
3. Verify empty — expects output parseable as `int`

The current blanket mock `lambda script: ("", 0)` returns `""` for the count query, which fails `int("")` at line 691. We take the "playlist doesn't exist" path (`-1`) which only needs 2 calls.

- [ ] **Step 1: Replace the blanket mock with a stateful mock**

Replace lines 684-687 of `tests/test_music_discovery.py` with:

```python
def test_setup_playlist_returns_true_on_success(monkeypatch):
    """Returns True when osascript succeeds."""
    responses = iter([("-1", 0), ("", 0)])
    monkeypatch.setattr(md, "_run_applescript", lambda script: next(responses))
    assert md.setup_playlist() is True
```

- [ ] **Step 2: Run the test to verify it passes**

Run: `python3 -m pytest tests/test_music_discovery.py::test_setup_playlist_returns_true_on_success -v`
Expected: PASS

- [ ] **Step 3: Run the full setup_playlist test group to check for regressions**

Run: `python3 -m pytest tests/test_music_discovery.py -k "setup_playlist" -v`
Expected: All 3 tests PASS (`test_setup_playlist_returns_true_on_success`, `test_setup_playlist_returns_false_on_failure`, `test_setup_playlist_script_references_playlist_name`)

- [ ] **Step 4: Commit**

```bash
git add tests/test_music_discovery.py
git commit -m "fix: test_setup_playlist mock returns parseable count"
```

---

### Task 2: Fix `test_add_track_to_playlist_returns_true_on_ok`

**Files:**
- Modify: `tests/test_music_discovery.py:707-713`

**Context:** `add_track_to_playlist()` (in `music_discovery.py:783`) calls `_run_applescript` 4 times on the success path:
1. Dedup check (line 807) — needs `"not_found"` to continue
2. Snapshot (line 828) — captures current track as `"name|||artist"`
3. Poll (line 846) — must differ from snapshot to break the loop
4. Add-to-playlist (line 875) — needs `"ok"` for success

The current blanket mock returns `("ok", 0)` for all calls. Snapshot and poll both return `"ok"`, so `out != prev_track` is never true and the `for...else` returns `False`.

- [ ] **Step 1: Replace the blanket mock with a stateful mock**

Replace lines 707-713 of `tests/test_music_discovery.py` with:

```python
def test_add_track_to_playlist_returns_true_on_ok(monkeypatch):
    """Returns True when full flow succeeds."""
    monkeypatch.setattr(md, "search_itunes", lambda a, t: "12345")
    monkeypatch.setattr(md, "_play_store_track", lambda sid: True)
    responses = iter([
        ("not_found", 0),          # dedup check
        ("Old|||Track", 0),        # snapshot current track
        ("Creep|||Radiohead", 0),  # poll — different from snapshot, breaks loop
        ("ok", 0),                 # add to library + playlist
    ])
    monkeypatch.setattr(md, "_run_applescript", lambda script: next(responses))
    monkeypatch.setattr("time.sleep", lambda s: None)
    assert md.add_track_to_playlist("Radiohead", "Creep") is True
```

- [ ] **Step 2: Run the test to verify it passes**

Run: `python3 -m pytest tests/test_music_discovery.py::test_add_track_to_playlist_returns_true_on_ok -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_music_discovery.py
git commit -m "fix: test_add_track mock uses correct 4-call sequence"
```

---

### Task 3: Fix `test_add_track_to_playlist_raises_on_osascript_failure`

**Files:**
- Modify: `tests/test_music_discovery.py:720-727`

**Context:** Same call sequence as Task 2, but the 4th call (add-to-playlist) returns `("", 1)` to trigger the `RuntimeError` at `music_discovery.py:876-877`. The current blanket mock `("", 1)` fails at the poll loop — empty string is falsy, so `out and out != prev_track` is always `False`, causing the `for...else` to return `False` before ever reaching the error-raising code.

- [ ] **Step 1: Replace the blanket mock with a stateful mock**

Replace lines 720-727 of `tests/test_music_discovery.py` with:

```python
def test_add_track_to_playlist_raises_on_osascript_failure(monkeypatch):
    """Raises RuntimeError when osascript returns non-zero."""
    monkeypatch.setattr(md, "search_itunes", lambda a, t: "12345")
    monkeypatch.setattr(md, "_play_store_track", lambda sid: True)
    responses = iter([
        ("not_found", 0),          # dedup check
        ("Old|||Track", 0),        # snapshot
        ("Creep|||Radiohead", 0),  # poll — breaks loop
        ("", 1),                   # add-to-playlist fails
    ])
    monkeypatch.setattr(md, "_run_applescript", lambda script: next(responses))
    monkeypatch.setattr("time.sleep", lambda s: None)
    with pytest.raises(RuntimeError):
        md.add_track_to_playlist("Radiohead", "Creep")
```

- [ ] **Step 2: Run the test to verify it passes**

Run: `python3 -m pytest tests/test_music_discovery.py::test_add_track_to_playlist_raises_on_osascript_failure -v`
Expected: PASS

- [ ] **Step 3: Run the full add_track_to_playlist test group**

Run: `python3 -m pytest tests/test_music_discovery.py -k "add_track_to_playlist" -v`
Expected: All 3 tests PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_music_discovery.py
git commit -m "fix: test_add_track_raises mock reaches error-raising code path"
```

---

### Task 4: Replace `test_get_machine_seed_random_mac_returns_none` with platform-specific tests

**Files:**
- Modify: `tests/test_music_discovery.py:883-887`

**Context:** `_get_machine_seed()` (in `music_discovery.py:165`) branches on `platform.system()`:
- `"Darwin"` → `subprocess.run(["ioreg", ...])` (line 177)
- `"Windows"` → `winreg.OpenKey(...)` (line 191)
- `"Linux"` → `pathlib.Path("/etc/machine-id").read_text()` (line 201)
- Falls through → returns `None` if `hw_uuid` is still `None`

The old test patches `uuid.getnode` which is never called — the function was rewritten to use platform-specific lookups. There is no `uuid.getnode` fallback.

Imports needed: `patch` and `MagicMock` are already imported at line 90 of the test file.

- [ ] **Step 1: Delete the old test and write three replacement tests**

Delete lines 883-887 (the old `test_get_machine_seed_random_mac_returns_none`) and replace with:

```python
def test_get_machine_seed_darwin_ioreg_fails_returns_none():
    """On macOS, if ioreg fails, returns None."""
    with patch("music_discovery.platform.system", return_value="Darwin"), \
         patch("music_discovery.subprocess.run", side_effect=Exception("no ioreg")):
        assert md._get_machine_seed() is None

def test_get_machine_seed_windows_registry_fails_returns_none():
    """On Windows, if registry read fails, returns None."""
    mock_winreg = MagicMock()
    mock_winreg.OpenKey = MagicMock(side_effect=Exception("no key"))
    mock_winreg.HKEY_LOCAL_MACHINE = 0x80000002
    with patch("music_discovery.platform.system", return_value="Windows"), \
         patch.dict("sys.modules", {"winreg": mock_winreg}):
        assert md._get_machine_seed() is None

def test_get_machine_seed_linux_no_machine_id_returns_none():
    """On Linux, if /etc/machine-id is missing, returns None."""
    with patch("music_discovery.platform.system", return_value="Linux"), \
         patch("music_discovery.pathlib.Path.read_text", side_effect=FileNotFoundError):
        assert md._get_machine_seed() is None
```

- [ ] **Step 2: Run the three new tests**

Run: `python3 -m pytest tests/test_music_discovery.py -k "machine_seed" -v`
Expected: All 3 new tests PASS

- [ ] **Step 3: Run full test suite to check for regressions**

Run: `python3 -m pytest tests/test_music_discovery.py -v`
Expected: All tests PASS (0 failures)

- [ ] **Step 4: Commit**

```bash
git add tests/test_music_discovery.py
git commit -m "fix: replace broken machine_seed test with platform-specific tests"
```
