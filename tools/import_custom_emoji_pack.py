import argparse
import asyncio
import re
import sys
from pathlib import Path
from typing import Any

from aiogram import Bot

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import settings_manager


DEFAULT_EMOJI_KEYS = {
    "🏠": "home",
    "👋": "hello",
    "📊": "status",
    "🧾": "history",
    "🧠": "models",
    "👥": "users",
    "🧩": "mcp",
    "🪪": "secretaries",
    "📄": "logs",
    "🕘": "actions",
    "⚙️": "settings",
    "◀️": "back",
    "▶️": "next",
    "🔎": "search",
}


def extract_sticker_set_name(value: str) -> str:
    text = (value or "").strip()
    if not text:
        raise ValueError("Sticker set link or name is required.")
    match = re.search(r"(?:https?://)?t\.me/addemoji/([^/?#]+)", text)
    if match:
        return match.group(1)
    return text


def _normalize_emoji(value: Any) -> str:
    return str(value or "").replace("\ufe0f", "")


async def import_custom_emoji_ids(set_link_or_name: str, *, dry_run: bool = False) -> dict[str, str]:
    token = str(settings_manager.get_settings().get("telegram_token") or "").strip()
    if not token:
        raise RuntimeError("telegram_token is empty in config.")

    set_name = extract_sticker_set_name(set_link_or_name)
    bot = Bot(token=token)
    try:
        sticker_set = await bot.get_sticker_set(set_name)
    finally:
        await bot.session.close()

    found: dict[str, str] = {}
    lookup = {_normalize_emoji(emoji): key for emoji, key in DEFAULT_EMOJI_KEYS.items()}
    for sticker in sticker_set.stickers:
        custom_id = getattr(sticker, "custom_emoji_id", None)
        key = lookup.get(_normalize_emoji(getattr(sticker, "emoji", "")))
        if custom_id and key and key not in found:
            found[key] = custom_id

    if not dry_run and found:
        settings = settings_manager.get_settings()
        telegram_menu = dict(settings.get("telegram_menu") or {})
        custom_ids = dict(telegram_menu.get("custom_emoji_ids") or {})
        custom_ids.update(found)
        telegram_menu["custom_emoji_ids"] = custom_ids
        settings_manager.settings["telegram_menu"] = telegram_menu
        settings_manager.save_settings()

    return found


def main() -> None:
    parser = argparse.ArgumentParser(description="Import Telegram custom emoji ids from a custom emoji set.")
    parser.add_argument("set", help="Sticker set name or t.me/addemoji/... link")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and print keys without changing config.json")
    args = parser.parse_args()

    found = asyncio.run(import_custom_emoji_ids(args.set, dry_run=args.dry_run))
    if not found:
        print("No matching custom emoji ids found.")
        return
    for key in sorted(found):
        print(f"{key}: {found[key]}")
    if not args.dry_run:
        print("config.json updated.")


if __name__ == "__main__":
    main()
