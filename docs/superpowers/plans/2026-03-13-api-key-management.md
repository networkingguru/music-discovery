# API Key Management Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add interactive first-run API key prompting with obfuscated `.env` storage, replacing the current error-and-exit flow.

**Architecture:** New encrypt/decrypt functions using XOR + SHA-256 hash of `uuid.getnode()`. A `prompt_for_api_key()` function handles the interactive flow. `load_dotenv()` gains `ENC:` prefix detection. Falls back to plain text if MAC address is unstable.

**Tech Stack:** Python stdlib only (`uuid`, `hashlib`, `getpass`, `re`, `os`, `pathlib`)

**Spec:** `docs/superpowers/specs/2026-03-13-api-key-management-design.md`

---

## Chunk 1: Core Encryption and Key Management

### Task 1: Create `.gitignore` and `.env.example`

**Files:**
- Create: `.gitignore`
- Create: `.env.example`

- [ ] **Step 1: Create `.gitignore`**

```
.env
__pycache__/
.pytest_cache/
*.pyc
.DS_Store
```

- [ ] **Step 2: Create `.env.example`**

```
# Last.fm API key (required)
# Get yours at: https://www.last.fm/api/account/create
LASTFM_API_KEY=

# Optional: override default cache/output directories
# CACHE_DIR=~/.cache/music_discovery
# OUTPUT_DIR=~/.cache/music_discovery
```

- [ ] **Step 3: Commit**

```bash
git add .gitignore .env.example
git commit -m "chore: add .gitignore and .env.example template"
```

---

### Task 2: Add `_get_machine_seed()` with tests

**Files:**
- Modify: `music_discovery.py` (add imports after line 18, `import datetime` — last stdlib import)
- Modify: `music_discovery.py` (add function after `load_dotenv()`, around line 92)
- Test: `tests/test_music_discovery.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_music_discovery.py`:

```python
def test_get_machine_seed_returns_32_bytes():
    seed = md._get_machine_seed()
    assert isinstance(seed, bytes)
    assert len(seed) == 32
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_music_discovery.py::test_get_machine_seed_returns_32_bytes -v`
Expected: FAIL with "AttributeError: module 'music_discovery' has no attribute '_get_machine_seed'"

- [ ] **Step 3: Write minimal implementation**

Add imports at the top of `music_discovery.py` (after line 18, `import datetime`):

```python
import uuid
import hashlib
import getpass
```

Add function after the `load_dotenv()` function (after line 91):

```python
def _get_machine_seed():
    """Return 32-byte SHA-256 hash of the machine's MAC address.
    Returns None if uuid.getnode() falls back to a random MAC
    (multicast bit set), since the seed would not be stable."""
    node = uuid.getnode()
    if node & (1 << 40):  # multicast bit = random fallback
        return None
    return hashlib.sha256(str(node).encode()).digest()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_music_discovery.py::test_get_machine_seed_returns_32_bytes -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add music_discovery.py tests/test_music_discovery.py
git commit -m "feat: add _get_machine_seed() for key encryption"
```

---

### Task 3: Add `encrypt_key()` and `decrypt_key()` with tests

**Files:**
- Modify: `music_discovery.py` (add functions after `_get_machine_seed()`)
- Test: `tests/test_music_discovery.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_music_discovery.py`:

```python
def test_encrypt_decrypt_round_trip():
    key = "888714dde5ecaef3354ef133d9320559"
    encrypted = md.encrypt_key(key)
    decrypted = md.decrypt_key(encrypted)
    assert decrypted == key

def test_encrypted_output_not_plaintext():
    key = "888714dde5ecaef3354ef133d9320559"
    encrypted = md.encrypt_key(key)
    assert key not in encrypted
```

Note: `test_decrypt_wrong_seed_fails_validation` is deferred to Task 4 since it
needs `_validate_api_key()` which is not yet implemented.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_music_discovery.py -k "encrypt" -v`
Expected: FAIL with "AttributeError: module 'music_discovery' has no attribute 'encrypt_key'"

- [ ] **Step 3: Write minimal implementation**

Add to `music_discovery.py` after `_get_machine_seed()`:

```python
def encrypt_key(plain):
    """XOR plain-text key against machine seed, return hex string.
    Raises RuntimeError if machine seed is unavailable."""
    seed = _get_machine_seed()
    if seed is None:
        raise RuntimeError("Cannot encrypt: no stable machine identifier")
    plain_bytes = plain.encode("utf-8")
    cipher = bytes(a ^ b for a, b in zip(plain_bytes, seed))
    return cipher.hex()


def decrypt_key(cipher_hex):
    """XOR hex-encoded cipher against machine seed, return plain text.
    Raises RuntimeError if machine seed is unavailable."""
    seed = _get_machine_seed()
    if seed is None:
        raise RuntimeError("Cannot decrypt: no stable machine identifier")
    cipher_bytes = bytes.fromhex(cipher_hex)
    plain = bytes(a ^ b for a, b in zip(cipher_bytes, seed))
    return plain.decode("utf-8")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_music_discovery.py -k "encrypt" -v`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add music_discovery.py tests/test_music_discovery.py
git commit -m "feat: add encrypt_key() and decrypt_key() with XOR obfuscation"
```

---

### Task 4: Add `_validate_api_key()` with tests

**Files:**
- Modify: `music_discovery.py` (add function after `decrypt_key()`)
- Test: `tests/test_music_discovery.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_music_discovery.py`:

```python
import hashlib
from unittest.mock import patch

def test_validate_api_key_accepts_valid():
    assert md._validate_api_key("888714dde5ecaef3354ef133d9320559") is True

def test_validate_api_key_rejects_short():
    assert md._validate_api_key("888714dde5ecaef3") is False

def test_validate_api_key_rejects_non_hex():
    assert md._validate_api_key("zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz") is False

def test_validate_api_key_rejects_empty():
    assert md._validate_api_key("") is False

def test_decrypt_wrong_seed_fails_validation():
    """Decrypting with wrong bytes produces output that fails validation."""
    key = "888714dde5ecaef3354ef133d9320559"
    encrypted = md.encrypt_key(key)
    # XOR with a different seed to simulate hardware change
    wrong_seed = hashlib.sha256(b"wrong").digest()
    cipher_bytes = bytes.fromhex(encrypted)
    bad_result = bytes(a ^ b for a, b in zip(cipher_bytes, wrong_seed))
    try:
        text = bad_result.decode("utf-8")
    except UnicodeDecodeError:
        text = ""
    assert not md._validate_api_key(text)

def test_get_machine_seed_random_mac_returns_none():
    """When uuid.getnode() returns a random MAC (multicast bit set), seed is None."""
    random_mac = 0x010000000000  # bit 40 set = multicast/random
    with patch("music_discovery.uuid.getnode", return_value=random_mac):
        assert md._get_machine_seed() is None
```

Note: add `import hashlib` and `from unittest.mock import patch` at the top of
the test file if not already present.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_music_discovery.py -k "validate_api" -v`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

Add to `music_discovery.py` after `decrypt_key()`:

```python
def _validate_api_key(key):
    """Return True if key looks like a valid Last.fm API key (32-char hex)."""
    return bool(re.match(r"^[0-9a-fA-F]{32}$", key))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_music_discovery.py -k "validate_api or wrong_seed or random_mac" -v`
Expected: 6 PASS

- [ ] **Step 5: Commit**

```bash
git add music_discovery.py tests/test_music_discovery.py
git commit -m "feat: add _validate_api_key() for key format validation"
```

---

## Chunk 2: Integration — Prompt Flow, `.env` Writing, and Main Wiring

### Task 5: Add `_write_key_to_env()` with tests

**Files:**
- Modify: `music_discovery.py` (add function after `_validate_api_key()`)
- Test: `tests/test_music_discovery.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_music_discovery.py`:

```python
def test_write_key_to_env_creates_new_file(tmp_path):
    env_path = tmp_path / ".env"
    md._write_key_to_env("ENC:abc123", env_path)
    assert env_path.read_text() == "LASTFM_API_KEY=ENC:abc123\n"

def test_write_key_to_env_appends_to_existing(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("CACHE_DIR=~/my_cache\n")
    md._write_key_to_env("ENC:abc123", env_path)
    content = env_path.read_text()
    assert "CACHE_DIR=~/my_cache" in content
    assert "LASTFM_API_KEY=ENC:abc123" in content

def test_write_key_to_env_replaces_existing_key(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("CACHE_DIR=~/my_cache\nLASTFM_API_KEY=old_value\nOUTPUT_DIR=~/out\n")
    md._write_key_to_env("ENC:new_value", env_path)
    content = env_path.read_text()
    assert "LASTFM_API_KEY=ENC:new_value" in content
    assert "old_value" not in content
    assert "CACHE_DIR=~/my_cache" in content
    assert "OUTPUT_DIR=~/out" in content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_music_discovery.py -k "write_key_to_env" -v`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

Add to `music_discovery.py` after `_validate_api_key()`:

```python
def _write_key_to_env(value, env_path=None):
    """Write LASTFM_API_KEY=<value> to .env file.
    Creates file if missing, appends if key absent, replaces if key exists."""
    if env_path is None:
        env_path = pathlib.Path(__file__).parent / ".env"
    env_path = pathlib.Path(env_path)

    key_line = f"LASTFM_API_KEY={value}\n"

    if not env_path.exists():
        env_path.write_text(key_line, encoding="utf-8")
        return

    lines = env_path.read_text(encoding="utf-8").splitlines(keepends=True)
    found = False
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("LASTFM_API_KEY=") or stripped == "LASTFM_API_KEY":
            new_lines.append(key_line)
            found = True
        else:
            new_lines.append(line)
    if not found:
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines.append("\n")
        new_lines.append(key_line)
    env_path.write_text("".join(new_lines), encoding="utf-8")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_music_discovery.py -k "write_key_to_env" -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add music_discovery.py tests/test_music_discovery.py
git commit -m "feat: add _write_key_to_env() with create/append/replace logic"
```

---

### Task 6: Add `prompt_for_api_key()` with tests

**Files:**
- Modify: `music_discovery.py` (add function after `_write_key_to_env()`)
- Test: `tests/test_music_discovery.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_music_discovery.py`:

```python
def test_prompt_for_api_key_success(tmp_path):
    env_path = tmp_path / ".env"
    with patch("music_discovery.getpass.getpass", return_value="888714dde5ecaef3354ef133d9320559"):
        result = md.prompt_for_api_key(env_path=env_path)
    assert result == "888714dde5ecaef3354ef133d9320559"
    content = env_path.read_text()
    # Should be encrypted (ENC: prefix) or plain depending on machine seed
    assert "LASTFM_API_KEY=" in content

def test_prompt_for_api_key_retries_on_invalid(tmp_path):
    env_path = tmp_path / ".env"
    with patch("music_discovery.getpass.getpass", side_effect=["bad", "also_bad", "888714dde5ecaef3354ef133d9320559"]):
        result = md.prompt_for_api_key(env_path=env_path)
    assert result == "888714dde5ecaef3354ef133d9320559"

def test_prompt_for_api_key_exits_after_3_failures(tmp_path):
    env_path = tmp_path / ".env"
    with patch("music_discovery.getpass.getpass", side_effect=["bad", "bad", "bad"]):
        result = md.prompt_for_api_key(env_path=env_path)
    assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_music_discovery.py -k "prompt_for_api" -v`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

Add to `music_discovery.py` after `_write_key_to_env()`:

```python
def prompt_for_api_key(env_path=None):
    """Interactive first-run prompt for the Last.fm API key.
    Validates, encrypts (if possible), writes to .env, returns plain key.
    Returns None after 3 failed attempts."""
    print("\n" + "=" * 60)
    print("  Last.fm API Key Required")
    print("=" * 60)
    print("\nThis tool uses the Last.fm API to filter and enrich results.")
    print("You need a free API key to continue.\n")
    print("  1. Go to: https://www.last.fm/api/account/create")
    print("  2. Log in (or create a free account)")
    print("  3. Fill in an application name and description (anything works)")
    print("  4. Copy the 'API Key' shown on the next page\n")

    for attempt in range(3):
        key = getpass.getpass("Enter your Last.fm API key: ").strip()
        if _validate_api_key(key):
            seed = _get_machine_seed()
            if seed is not None:
                value = "ENC:" + encrypt_key(key)
            else:
                print("NOTE: Could not detect stable hardware ID.")
                print("      Key will be stored in plain text.")
                value = key
            _write_key_to_env(value, env_path)
            print("API key saved to .env successfully.\n")
            return key
        remaining = 2 - attempt
        if remaining > 0:
            print(f"Invalid key (must be 32 hex characters). {remaining} attempt(s) left.")
        else:
            print("Invalid key. No attempts remaining.")
            print("Get your key at: https://www.last.fm/api/account/create")
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_music_discovery.py -k "prompt_for_api" -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add music_discovery.py tests/test_music_discovery.py
git commit -m "feat: add prompt_for_api_key() interactive first-run flow"
```

---

### Task 7: Update `load_dotenv()` to handle `ENC:` prefix

**Files:**
- Modify: `music_discovery.py:67-91` (the existing `load_dotenv()` function)
- Test: `tests/test_music_discovery.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_music_discovery.py`:

```python
def test_load_dotenv_decrypts_enc_prefix(tmp_path, monkeypatch):
    key = "888714dde5ecaef3354ef133d9320559"
    encrypted = md.encrypt_key(key)
    env_path = tmp_path / ".env"
    env_path.write_text(f"LASTFM_API_KEY=ENC:{encrypted}\n")
    monkeypatch.delenv("LASTFM_API_KEY", raising=False)
    md.load_dotenv(env_path)
    assert os.environ.get("LASTFM_API_KEY") == key
    # Clean up
    monkeypatch.delenv("LASTFM_API_KEY", raising=False)

def test_load_dotenv_plain_text_backward_compat(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text("LASTFM_API_KEY=888714dde5ecaef3354ef133d9320559\n")
    monkeypatch.delenv("LASTFM_API_KEY", raising=False)
    md.load_dotenv(env_path)
    assert os.environ.get("LASTFM_API_KEY") == "888714dde5ecaef3354ef133d9320559"
    # Clean up
    monkeypatch.delenv("LASTFM_API_KEY", raising=False)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_music_discovery.py -k "load_dotenv" -v`
Expected: The `ENC:` test should fail (key returned with `ENC:` prefix still attached)

- [ ] **Step 3: Modify `load_dotenv()` implementation**

In `music_discovery.py`, replace the `load_dotenv()` function (lines 67-91) with:

```python
def load_dotenv(dotenv_path=None):
    """Load .env file into os.environ. Keys already in env are not overwritten.
    dotenv_path defaults to a .env file next to this script.
    Detects ENC: prefix on LASTFM_API_KEY and decrypts it.
    Prints a note if .env is missing and points to .env.example."""
    if dotenv_path is None:
        dotenv_path = pathlib.Path(__file__).parent / ".env"
    path = pathlib.Path(dotenv_path)
    if not path.exists():
        print(f"NOTE: No .env file found at {path}.")
        print("      Copy .env.example → .env and fill in your settings.")
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key   = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            # Decrypt ENC:-prefixed values for LASTFM_API_KEY
            if key == "LASTFM_API_KEY" and value.startswith("ENC:"):
                try:
                    value = decrypt_key(value[4:])
                    if not _validate_api_key(value):
                        print("WARNING: Stored key could not be decrypted (hardware change?).")
                        print("         Please re-enter your API key.")
                        value = ""
                except Exception:
                    print("WARNING: Failed to decrypt stored API key.")
                    value = ""
            if key and key not in os.environ:
                os.environ[key] = value
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_music_discovery.py -k "load_dotenv" -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `python3 -m pytest tests/test_music_discovery.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add music_discovery.py tests/test_music_discovery.py
git commit -m "feat: update load_dotenv() to decrypt ENC: prefixed API keys"
```

---

### Task 8: Wire `prompt_for_api_key()` into `main()`

**Files:**
- Modify: `music_discovery.py:687-691` (the api_key check in `main()`)

- [ ] **Step 1: Replace the error-and-exit block**

In `music_discovery.py`, replace lines 687-691:

```python
    api_key = os.environ.get("LASTFM_API_KEY", "").strip()
    if not api_key:
        print("ERROR: LASTFM_API_KEY not set.")
        print("Add it to your .env file (see .env.example).")
        return
```

with:

```python
    api_key = os.environ.get("LASTFM_API_KEY", "").strip()
    if not api_key:
        api_key = prompt_for_api_key()
        if not api_key:
            return
```

- [ ] **Step 2: Add `.env.example` creation to `prompt_for_api_key()`**

Add to `prompt_for_api_key()` in `music_discovery.py`, inside the success branch just before `return key`:

```python
            # Create .env.example if it doesn't exist
            example_path = pathlib.Path(__file__).parent / ".env.example"
            if not example_path.exists():
                example_path.write_text(
                    "# Last.fm API key (required)\n"
                    "# Get yours at: https://www.last.fm/api/account/create\n"
                    "LASTFM_API_KEY=\n"
                    "\n"
                    "# Optional: override default cache/output directories\n"
                    "# CACHE_DIR=~/.cache/music_discovery\n"
                    "# OUTPUT_DIR=~/.cache/music_discovery\n",
                    encoding="utf-8",
                )
```

- [ ] **Step 3: Run full test suite**

Run: `python3 -m pytest tests/test_music_discovery.py -v`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add music_discovery.py
git commit -m "feat: wire prompt_for_api_key() into main() for first-run setup"
```

---

### Task 9: Final verification and cleanup

- [ ] **Step 1: Run full test suite**

Run: `python3 -m pytest tests/test_music_discovery.py -v`
Expected: All tests PASS

- [ ] **Step 2: Verify `.gitignore` excludes `.env`**

Run: `git status` and confirm `.env` does not appear in untracked files (if one exists).

- [ ] **Step 3: Verify the first-run flow manually (smoke test)**

Temporarily rename `.env` if it exists, then run:
```bash
python3 music_discovery.py
```
Expected: See the API key prompt with instructions and URL. Enter a key, confirm it's saved to `.env` with `ENC:` prefix.

- [ ] **Step 4: Final commit if any cleanup needed**

```bash
git add -A
git commit -m "chore: final cleanup for API key management feature"
```
