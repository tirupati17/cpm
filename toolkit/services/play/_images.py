"""Play listing image checks and layout. Pure logic, no network and no secrets."""
import struct
from pathlib import Path

# device -> (screenshot imageType, graphic imageType, graphic size, default graphic file)
DEVICES = {
    'phone': ('phoneScreenshots', 'featureGraphic', (1024, 500), 'feature-graphic.png'),
    'tablet7': ('sevenInchScreenshots', None, None, None),
    'tablet10': ('tenInchScreenshots', None, None, None),
    'tv': ('tvScreenshots', 'tvBanner', (1280, 720), 'tv-banner.png'),
    'wear': ('wearScreenshots', None, None, None),
}
# Play shows at most eight screenshots per device type.
MAX_SHOTS = 8


def png_size(file):
    """(width, height) of a PNG, refusing anything Play would reject later."""
    raw = Path(file).read_bytes()[:26]
    if raw[:8] != b'\x89PNG\r\n\x1a\n':
        raise SystemExit(f'{file} is not a PNG.')
    width, height, depth, color = struct.unpack('>IIBB', raw[16:26])
    if depth != 8 or color != 2:
        raise SystemExit(f'{file}: Play requires 24-bit PNG without alpha (got bit depth {depth}, colour type {color}).')
    return width, height


def parse_size(text):
    try:
        width, height = (int(v) for v in text.lower().split('x'))
        return width, height
    except ValueError:
        raise SystemExit(f'Size must look like 1080x1920, got {text!r}.')


def check_screenshot(file, exact=None):
    """Exact size when given, else Play's bounds: 320..3840 px a side, at most 2:1."""
    width, height = png_size(file)
    if exact:
        if (width, height) != exact:
            raise SystemExit(f'{file} is {width}x{height}, expected {exact[0]}x{exact[1]}.')
        return width, height
    if not (320 <= min(width, height) and max(width, height) <= 3840):
        raise SystemExit(f'{file} is {width}x{height}; Play wants 320 to 3840 px per side.')
    if max(width, height) > 2 * min(width, height):
        raise SystemExit(f'{file} is {width}x{height}; Play allows at most a 2:1 aspect ratio.')
    return width, height


def select_shots(folder, names=None, exclude=()):
    """The screenshots to upload, in order.

    With names, exactly those files in that order (the story the listing tells).
    Without, every PNG in the folder sorted by name, minus the graphic. More than
    Play's eight is refused rather than silently truncated.
    """
    folder = Path(folder)
    if names:
        shots = [folder / name for name in names]
        missing = [s.name for s in shots if not s.is_file()]
        if missing:
            raise SystemExit(f'{folder} is missing {", ".join(missing)}.')
    else:
        shots = sorted(p for p in folder.glob('*.png') if p.name not in exclude)
    if not shots:
        raise SystemExit(f'No screenshots in {folder}.')
    if len(shots) > MAX_SHOTS:
        raise SystemExit(f'{folder} has {len(shots)} screenshots; Play shows at most {MAX_SHOTS}. '
                         'Pass --shots to choose which, in order.')
    return shots


def parse_locale_map(text):
    """'en=en-US,hi=hi-IN' -> {'en': 'en-US', 'hi': 'hi-IN'}"""
    mapping = {}
    for pair in filter(None, (text or '').split(',')):
        folder, _, locale = pair.partition('=')
        if not locale:
            raise SystemExit(f'--locale-map entries look like folder=play-code, got {pair!r}.')
        mapping[folder.strip()] = locale.strip()
    return mapping


def targets(root, listed, languages=None, locale_map=None):
    """[(play language, folder)] to update.

    Two layouts. If root itself holds PNGs, that one set goes to every language
    (default: every language Play already lists; --languages are Play codes).
    Otherwise each subfolder is a language (named for its Play code, or mapped by
    --locale-map; --languages are folder names), and by default only folders
    whose language already has a Play listing are touched.
    """
    root = Path(root)
    if not root.is_dir():
        raise SystemExit(f'No image folder at {root}.')
    if any(root.glob('*.png')):
        return [(locale, root) for locale in (languages or sorted(listed))]
    mapping = locale_map or {}
    folders = sorted(d.name for d in root.iterdir() if d.is_dir())
    names = languages or [n for n in folders if mapping.get(n, n) in listed]
    for name in names:
        if not (root / name).is_dir():
            raise SystemExit(f'No folder {root / name}.')
    return [(mapping.get(n, n), root / n) for n in names]
