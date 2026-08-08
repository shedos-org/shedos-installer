"""Keep /etc/vconsole.conf naming a keymap loadkeys can actually load."""

from pathlib import Path


def sanitize_keymap(root_mount) -> bool:
    """Fall back to `us` when vconsole.conf names a console-less keymap.

    Calamares' keyboard module writes the chosen X11 layout, but some
    layouts (`ng`, `in`, …) have no keymap under /usr/share/kbd/keymaps.
    loadkeys then fails, and because sd-vconsole bakes this file into the
    initramfs, Virtual Console Setup fails on every boot until the next
    initramfs regeneration. Such layouts are US-ASCII at the console
    anyway (their extra glyphs live on AltGr), so `us` is faithful. A
    keymap that exists is left strictly alone.

    Returns True when the file was rewritten. Raises OSError if the file
    cannot be read or written.
    """
    root = Path(root_mount)
    vconsole = root / "etc" / "vconsole.conf"
    if not vconsole.exists():
        return False

    keymaps_root = root / "usr" / "share" / "kbd" / "keymaps"
    lines = []
    changed = False
    for line in vconsole.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("KEYMAP="):
            keymap = stripped.partition("=")[2].strip().strip('"').strip("'")
            has_map = bool(keymap) and keymaps_root.is_dir() and any(
                keymaps_root.rglob(f"{keymap}.map*")
            )
            if keymap and keymap != "us" and not has_map:
                lines.append("KEYMAP=us")
                changed = True
                continue
        lines.append(line)

    if not changed:
        return False
    vconsole.write_text("\n".join(lines) + "\n")
    return True
