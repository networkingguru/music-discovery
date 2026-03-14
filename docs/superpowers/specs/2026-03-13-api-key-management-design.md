# API Key Management Design

## Goal

Replace the current "missing key → error" flow with an interactive first-run
experience that prompts the user for their Last.fm API key, encrypts it, and
stores it in `.env` automatically. The key should not be visible in plain text
if someone opens the file.

## First-Run Flow

When the script starts and no valid `LASTFM_API_KEY` is found in the
environment or `.env`:

1. Print a message explaining that a Last.fm API key is required.
2. Show the signup URL: `https://www.last.fm/api/account/create`
3. Provide brief directions: create an account (or log in), create an API
   application (name/description can be anything), and copy the API Key shown.
4. Prompt using `getpass.getpass("Enter your Last.fm API key: ")` so the key
   is not visible on screen as the user types.
5. Validate the input — must be a 32-character hex string.
6. Encrypt using XOR + machine seed (see below).
7. Write `LASTFM_API_KEY=ENC:<hex>` to `.env`:
   - If `.env` does not exist: create it with just the key line.
   - If `.env` exists but has no `LASTFM_API_KEY`: append the line.
   - If `.env` exists and already has `LASTFM_API_KEY`: replace that line
     in-place, preserving all other content.
8. Create `.env.example` if it does not already exist.
9. Continue running the script normally with the decrypted key.

If validation fails, re-prompt with an error message (up to 3 attempts, then
exit with a helpful message).

## Encryption Scheme

**Threat model:** Prevent casual inspection of the `.env` file. Not designed to
resist a determined attacker with machine access.

**Encrypt:**

1. Get machine seed: `uuid.getnode()` (MAC address as integer, cross-platform).
   - **Random MAC detection:** Check `is_random = uuid.getnode() & (1 << 40)`.
     If the multicast bit is set, the value is a random fallback (no real NIC).
     In this case, warn the user and store the key in plain text instead of
     encrypting, since the seed would not be stable across runs.
2. Hash with SHA-256: `hashlib.sha256(str(uuid.getnode()).encode()).digest()`
   — produces 32 bytes, matching a 32-char API key.
3. XOR each byte of the UTF-8-encoded API key against the corresponding byte
   of the hash.
4. Encode the XOR result as a hex string.
5. Store as `LASTFM_API_KEY=ENC:<hex>`.

**Decrypt:**

1. Detect the `ENC:` prefix when reading from `.env`.
2. Decode the hex string after `ENC:`.
3. XOR against the same SHA-256 hash of `uuid.getnode()`.
4. Decode the result as UTF-8 to recover the plain-text key.
5. **Post-decryption validation:** Verify the result is a 32-character hex
   string. If not (e.g., hardware changed, new NIC), print a clear message:
   "Stored key could not be decrypted (hardware change?). Please re-enter
   your API key." Then re-run the prompt flow (same 3-attempt limit).

**Backward compatibility:** If the value in `.env` has no `ENC:` prefix, it is
treated as a plain-text key and used directly. This supports users who prefer
to manage their own `.env` manually.

## File Changes

### Modified: `music_discovery.py`

New functions (all stdlib, no new dependencies):

- `encrypt_key(plain: str) -> str` — returns hex-encoded XOR ciphertext.
- `decrypt_key(cipher_hex: str) -> str` — returns plain-text key.
- `prompt_for_api_key() -> str` — interactive first-run prompt with
  validation; returns the plain-text key and writes encrypted `.env`.

Modified functions:

- `load_dotenv()` — after loading `.env`, detect `ENC:` prefix on
  `LASTFM_API_KEY` and decrypt before setting `os.environ`.
- `main()` — when `LASTFM_API_KEY` is missing after `load_dotenv()`, call
  `prompt_for_api_key()` instead of exiting with an error.

### Created: `.env.example`

```
# Last.fm API key (required)
# Get yours at: https://www.last.fm/api/account/create
LASTFM_API_KEY=

# Optional: override default cache/output directories
# CACHE_DIR=~/.cache/music_discovery
# OUTPUT_DIR=~/.cache/music_discovery
```

### Created: `.gitignore` (project root)

```
.env
__pycache__/
.pytest_cache/
*.pyc
.DS_Store
```

## Testing

- `test_encrypt_decrypt_round_trip` — encrypt then decrypt returns original key.
- `test_encrypted_output_not_plaintext` — encrypted hex does not contain the
  original key string.
- `test_plain_text_backward_compat` — a value without `ENC:` prefix is returned
  as-is by `load_dotenv()`.
- `test_invalid_key_rejected` — keys that are not 32-char hex are rejected by
  validation.
- `test_decrypt_wrong_seed_fails_validation` — decrypting with a different
  seed produces output that fails the 32-char hex validation check.

## Dependencies

None. Uses only Python stdlib: `uuid`, `hashlib`, `os`, `pathlib`, `getpass`,
`re`.
