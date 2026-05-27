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
    """Reference an earlier action's output (Magic Variable)."""
    return {
        "Value": {
            "OutputUUID": output_uuid,
            "Type": "ActionOutput",
            "OutputName": output_name,
        },
        "WFSerializationType": "WFTokenAttachment",
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
    """Build a 5-action shortcut: Record Audio → POST → extract `text` → Clipboard → Notify."""
    record_uuid = _uuid()
    download_uuid = _uuid()
    dict_value_uuid = _uuid()

    actions = [
        # 1. Record Audio
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
        # 2. Get Contents of URL — POST multipart with audio file
        {
            "WFWorkflowActionIdentifier": "is.workflow.actions.downloadurl",
            "WFWorkflowActionParameters": {
                "UUID": download_uuid,
                "CustomOutputName": "Server Response",
                "WFURL": url,
                "WFHTTPMethod": "POST",
                "WFHTTPBodyType": "Form",
                "ShowHeaders": False,
                "WFFormValues": {
                    "Value": {
                        "WFDictionaryFieldValueItems": [
                            {
                                # WFItemType: 0=Text, 4=Number, 5=Date, 6=File
                                "WFItemType": 6,
                                "WFKey": _text_token("audio"),
                                "WFValue": _attach(record_uuid, "Recorded Audio"),
                            }
                        ]
                    },
                    "WFSerializationType": "WFDictionaryFieldValue",
                },
            },
        },
        # 3. Get Dictionary Value (key=text)
        {
            "WFWorkflowActionIdentifier": "is.workflow.actions.getvalueforkey",
            "WFWorkflowActionParameters": {
                "UUID": dict_value_uuid,
                "CustomOutputName": "Transcript",
                "WFGetDictionaryValueType": "Value",
                "WFDictionaryKey": "text",
                "WFInput": _attach(download_uuid, "Server Response"),
            },
        },
    ]

    if mode == "dict":
        # 4. Copy to Clipboard
        actions.append(
            {
                "WFWorkflowActionIdentifier": "is.workflow.actions.setclipboard",
                "WFWorkflowActionParameters": {
                    "WFInput": _attach(dict_value_uuid, "Transcript"),
                    "WFLocalOnly": True,
                },
            }
        )
        # 5. Show Notification with the transcript
        actions.append(
            {
                "WFWorkflowActionIdentifier": "is.workflow.actions.notification",
                "WFWorkflowActionParameters": {
                    "WFNotificationActionTitle": "Govori",
                    "WFNotificationActionBody": _text_with_attachment(
                        "✓ ", dict_value_uuid, "Transcript"
                    ),
                    "WFNotificationActionSound": False,
                },
            }
        )
    elif mode == "note":
        # 4. Vibrate (quick haptic) — note is fire-and-forget, no clipboard
        actions.append(
            {
                "WFWorkflowActionIdentifier": "is.workflow.actions.vibrate",
                "WFWorkflowActionParameters": {},
            }
        )
        # 5. Show Notification with transcript preview
        actions.append(
            {
                "WFWorkflowActionIdentifier": "is.workflow.actions.notification",
                "WFWorkflowActionParameters": {
                    "WFNotificationActionTitle": "Govori — заметка сохранена",
                    "WFNotificationActionBody": _text_with_attachment(
                        "", dict_value_uuid, "Transcript"
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

    for name, mode, filename in [
        ("Govori Dict", "dict", "Govori_Dict.shortcut"),
        ("Govori Note", "note", "Govori_Note.shortcut"),
    ]:
        url = args.url.rstrip("/") + ("/dict" if mode == "dict" else "/note")
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
