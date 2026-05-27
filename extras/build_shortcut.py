"""Generate .shortcut files (Apple Shortcuts plist) for govori iPhone integration.

Outputs ./Govori_Dict.shortcut and ./Govori_Note.shortcut next to this script.
Open one on iPhone (AirDrop / iCloud Drive / Files app) — Shortcuts.app will
offer to import. You need to enable Settings → Shortcuts → "Allow Untrusted
Shortcuts" first, since these are unsigned.

Re-run after changing URL/port:
    python3 extras/build_shortcut.py --url http://100.121.161.56:8765
"""
from __future__ import annotations

import argparse
import plistlib
import uuid
from pathlib import Path


def _uuid() -> str:
    return str(uuid.uuid4()).upper()


def _text_token(s: str) -> dict:
    """Wrap a plain string as Shortcuts' WFTextTokenString."""
    return {
        "Value": {"string": s, "attachmentsByRange": {}},
        "WFSerializationType": "WFTextTokenString",
    }


def _attach(output_uuid: str, output_name: str) -> dict:
    """Pure WFTokenAttachment — for File/Value fields in form-data items."""
    return {
        "Value": {
            "OutputUUID": output_uuid,
            "Type": "ActionOutput",
            "OutputName": output_name,
        },
        "WFSerializationType": "WFTokenAttachment",
    }


def _var_input(output_uuid: str, output_name: str) -> dict:
    """WFTextTokenString with single-attachment-at-pos-0 — for action `WFInput` fields.

    Apple's Shortcuts silently drops pure WFTokenAttachment values used as
    WFInput, rendering the action's default placeholder ("Контент", "Словарь")
    and effectively passing nothing. WFInput must be a text-style attachment
    even when the "text" is just a single magic-variable reference.
    """
    return {
        "Value": {
            "string": "￼",  # Object Replacement Character
            "attachmentsByRange": {
                "{0, 1}": {
                    "OutputUUID": output_uuid,
                    "Type": "ActionOutput",
                    "OutputName": output_name,
                }
            },
        },
        "WFSerializationType": "WFTextTokenString",
    }


def _text_with_attachment(prefix: str, output_uuid: str, output_name: str) -> dict:
    """Build a WFTextTokenString of `prefix` + magic variable inline.

    Shortcut format uses an Object Replacement Character (U+FFFC) at the
    attachment position, plus an attachmentsByRange map keyed by `{pos, 1}`.
    """
    placeholder = "￼"
    body = f"{prefix}{placeholder}"
    pos = len(prefix)
    return {
        "Value": {
            "string": body,
            "attachmentsByRange": {
                f"{{{pos}, 1}}": {
                    "OutputUUID": output_uuid,
                    "Type": "ActionOutput",
                    "OutputName": output_name,
                }
            },
        },
        "WFSerializationType": "WFTextTokenString",
    }


def build_shortcut(name: str, url: str, mode: str) -> dict:
    """Build a 4-action shortcut relying on Shortcuts AUTO-CHAINING.

    Record Audio → POST (raw File body) → Set Clipboard → Notification.

    Design notes (learned the hard way):
    - Server is hit with ?text=1 so the response is `text/plain` — the response
      IS the transcript. No "Get Dictionary Value", no JSON key extraction.
    - Actions with NO `WFInput` automatically receive the previous action's
      output (the canonical Shortcuts model). This sidesteps the fragile
      WFTokenAttachment / WFTextTokenString encoding that silently dropped
      magic-variable wires in earlier versions.
    - Request body is `File` (raw bytes), not multipart Form — removes the one
      remaining magic-variable reference (the audio file form item).
    - Only the notification body keeps an explicit output reference, via
      _text_with_attachment, which is the one encoding confirmed to render.
    """
    record_uuid = _uuid()
    download_uuid = _uuid()

    actions = [
        # 1. Record Audio (output auto-feeds the next action)
        {
            "WFWorkflowActionIdentifier": "is.workflow.actions.recordaudio",
            "WFWorkflowActionParameters": {
                "UUID": record_uuid,
                "CustomOutputName": "Recorded Audio",
                "WFRecordingStart": "On Tap",
                "WFRecordingEnd": "On Tap",
                "WFRecordingCompression": "Normal",
                "WFRecordingQuality": "Normal",
            },
        },
        # 2. Get Contents of URL — POST raw audio body, no explicit input
        #    (auto-chains Recorded Audio as the File body). Returns plain text.
        {
            "WFWorkflowActionIdentifier": "is.workflow.actions.downloadurl",
            "WFWorkflowActionParameters": {
                "UUID": download_uuid,
                "CustomOutputName": "Transcript",
                "WFURL": url,
                "WFHTTPMethod": "POST",
                "WFHTTPBodyType": "File",
                "ShowHeaders": False,
            },
        },
    ]

    if mode == "dict":
        # 3. Copy to Clipboard — no WFInput, auto-chains the plain-text response
        actions.append(
            {
                "WFWorkflowActionIdentifier": "is.workflow.actions.setclipboard",
                "WFWorkflowActionParameters": {"WFLocalOnly": True},
            }
        )
        # 4. Show Notification — body references the URL output (renders reliably)
        actions.append(
            {
                "WFWorkflowActionIdentifier": "is.workflow.actions.notification",
                "WFWorkflowActionParameters": {
                    "WFNotificationActionTitle": "Govori",
                    "WFNotificationActionBody": _text_with_attachment(
                        "✓ ", download_uuid, "Transcript"
                    ),
                    "WFNotificationActionSound": False,
                },
            }
        )
    elif mode == "note":
        # 3. Vibrate — note is fire-and-forget, no clipboard
        actions.append(
            {
                "WFWorkflowActionIdentifier": "is.workflow.actions.vibrate",
                "WFWorkflowActionParameters": {},
            }
        )
        # 4. Show Notification with the server's plain-text confirmation
        actions.append(
            {
                "WFWorkflowActionIdentifier": "is.workflow.actions.notification",
                "WFWorkflowActionParameters": {
                    "WFNotificationActionTitle": "Govori — заметка",
                    "WFNotificationActionBody": _text_with_attachment(
                        "", download_uuid, "Transcript"
                    ),
                    "WFNotificationActionSound": False,
                },
            }
        )

    return {
        "WFWorkflowClientVersion": "2700.4.0.1",
        "WFWorkflowMinimumClientVersion": 900,
        "WFWorkflowMinimumClientVersionString": "900",
        # Icon: orange-ish + microphone glyph (59446)
        "WFWorkflowIconStartColor": 2071128575,
        "WFWorkflowIconGlyphNumber": 59446,
        "WFWorkflowTypes": [],
        "WFWorkflowInputContentItemClasses": [
            "WFAppContentItem",
            "WFAppStoreAppContentItem",
            "WFArticleContentItem",
            "WFContactContentItem",
            "WFDateContentItem",
            "WFEmailAddressContentItem",
            "WFGenericFileContentItem",
            "WFImageContentItem",
            "WFiTunesProductContentItem",
            "WFLocationContentItem",
            "WFDCMapsLinkContentItem",
            "WFAVAssetContentItem",
            "WFPDFContentItem",
            "WFPhoneNumberContentItem",
            "WFRichTextContentItem",
            "WFSafariWebPageContentItem",
            "WFStringContentItem",
            "WFURLContentItem",
        ],
        "WFWorkflowImportQuestions": [],
        "WFWorkflowActions": actions,
        "WFWorkflowName": name,
    }


def _sign(path: Path) -> Path:
    """Wrap an unsigned .shortcut plist into Apple's signed binary format.

    Required because iOS 17+ refuses to import unsigned shortcuts from
    AirDrop / Files / iCloud Drive — error: "Импорт неподписанных быстрых
    команд не поддерживается". macOS Shortcuts.app accepts unsigned, but
    that doesn't help when targeting iPhone.
    `shortcuts sign --mode anyone` is the only path that lets the file be
    imported by anyone, not just contacts in your address book.
    """
    import subprocess

    signed = path.with_name(path.stem + "_signed.shortcut")
    res = subprocess.run(
        ["/usr/bin/shortcuts", "sign", "--mode", "anyone",
         "--input", str(path), "--output", str(signed)],
        capture_output=True, text=True,
    )
    if res.returncode != 0:
        # ERROR lines about "Unrecognized attribute string flag" are benign
        # Foundation warnings — only fail on non-zero exit.
        print(f"  ! sign failed (rc={res.returncode}): {res.stderr.strip()[:200]}")
        return path
    return signed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--url",
        default="http://100.121.161.56:8765",
        help="Relay base URL (Tailscale IP of VPS, port 8765 by default)",
    )
    parser.add_argument(
        "--out-dir",
        default=str(Path(__file__).parent),
        help="Where to write the .shortcut files",
    )
    parser.add_argument(
        "--no-sign",
        action="store_true",
        help="Skip Apple signing step (iPhone import will fail; mac-only)",
    )
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    targets = [
        ("Govori Dict",      "dict", "/dict?text=1",      "Govori_Dict.shortcut"),
        ("Govori Note",      "note", "/note?text=1",      "Govori_Note.shortcut"),
        ("Govori Dict TEST", "dict", "/dict-test?text=1", "Govori_DictTest.shortcut"),
    ]
    for name, mode, path_suffix, filename in targets:
        url = args.url.rstrip("/") + path_suffix
        sc = build_shortcut(name=name, url=url, mode=mode)
        path = out_dir / filename
        with path.open("wb") as f:
            plistlib.dump(sc, f, fmt=plistlib.FMT_XML)
        if args.no_sign:
            print(f"✓ {path}  →  POST {url}  (unsigned)")
        else:
            signed = _sign(path)
            print(f"✓ {signed}  →  POST {url}  (signed, iPhone-ready)")


if __name__ == "__main__":
    main()
