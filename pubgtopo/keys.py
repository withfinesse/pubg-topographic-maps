"""AES key handling for the `unpack` stage.

The pak AES key is NEVER stored in this repository. Supply it either with
the `--key` command-line option or via the PUBG_PAK_KEY environment
variable (the FModel pattern: the tool ships without the key, the user
provides their own).

Accepted forms, all normalised to the 32 key bytes:

* the 32-character string itself -> its UTF-8 (ASCII) bytes are the key
* 64 hex characters              -> hex-decoded
* base64 of the 32 key bytes     -> base64-decoded

Watch out for the classic trap (see README, "The AES key"): PUBG's key is
a string that merely *looks* like hex — the key bytes are the ASCII text
of the string. That is also why the hex form works: written as hex, the
published value is the hex encoding *of that ASCII text*, so hex-decoding
it lands on the right bytes. What does NOT work is treating the string as
if it were the hex representation of some other key material.
"""

import base64
import binascii
import os

ENV_VAR = "PUBG_PAK_KEY"


def normalize_key(value):
    """Turn any accepted textual form of the key into 32 bytes."""
    v = value.strip()
    if v.lower().startswith("0x"):
        v = v[2:]

    raw = None
    if len(v) == 64:
        try:
            raw = binascii.unhexlify(v)
        except binascii.Error:
            raw = None
    if raw is None and len(v.encode("utf-8")) == 32:
        raw = v.encode("utf-8")
    if raw is None:
        try:
            decoded = base64.b64decode(v, validate=True)
            if len(decoded) == 32:
                raw = decoded
        except Exception:
            raw = None

    if raw is None or len(raw) != 32:
        raise ValueError(
            "could not interpret the supplied AES key: expected a 32-character "
            "string, 64 hex characters, or base64 of 32 bytes"
        )
    return raw


def resolve_key(cli_value=None):
    """Key from --key if given, else from the PUBG_PAK_KEY env var."""
    value = cli_value or os.environ.get(ENV_VAR)
    if not value:
        raise SystemExit(
            f"No AES key supplied. Pass --key or set the {ENV_VAR} environment "
            "variable. The key is a widely published, community-known value for "
            "TslGame paks; this tool deliberately ships without it — see the "
            "README section 'The AES key'."
        )
    try:
        return normalize_key(value)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
