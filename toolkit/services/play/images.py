#!/usr/bin/env python3
"""Replace a Play listing's screenshots and graphic per language (phone, tablet, TV, Wear).

    cpm play images --dir store-images                       # rehearse: upload, validate, discard
    cpm play images --dir store-images --commit              # replace the live images
    cpm play images --device tv --dir play-assets/tv --commit
    cpm play images --dir kit --locale-map en=en-US,hi=hi-IN --languages en,hi

Folder layout, either:
  <dir>/<language>/*.png   one set per language; folders are Play language codes
                           or mapped with --locale-map. Default: every folder
                           whose language already has a Play listing.
  <dir>/*.png              one set for every language Play lists (for example
                           TV screenshots shown in one language everywhere).

Screenshots are every PNG in the folder sorted by name, or exactly --shots in
that order. Play shows at most eight per device, so more is refused rather than
truncated. The graphic (phone: feature-graphic.png, 1024x500; TV: tv-banner.png,
1280x720) is uploaded when present, and required when named with --graphic.
Every image must be a 24-bit PNG without alpha; --size pins the screenshot size.

Only languages that already have a Play listing are touched. --create-listings
adds a missing one from <language folder>/metadata.json (title,
shortDescription, fullDescription) first; a new listing language is a reviewed
step, not a side effect. Adding a form factor (TV, Wear) and sending it for
review are Play Console steps; the API has no call for them.
"""
import argparse
import json
from pathlib import Path

import _play
from _images import DEVICES, check_screenshot, parse_locale_map, parse_size, png_size, select_shots, targets
from _listing import LIMITS, problems

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument('--dir', required=True, help='image folder (see layouts above)')
parser.add_argument('--device', choices=sorted(DEVICES), default='phone', help='which screenshots (default phone)')
parser.add_argument('--commit', action='store_true', help='actually replace the images; without it nothing changes')
parser.add_argument('--languages', help='comma separated folder names (or Play codes in the shared layout)')
parser.add_argument('--locale-map', help='folder=play-code pairs, e.g. en=en-US,zh-Hans=zh-CN')
parser.add_argument('--shots', help='comma separated screenshot file names, in listing order')
parser.add_argument('--size', help='required screenshot size, e.g. 1080x1920 (default: Play bounds only)')
parser.add_argument('--graphic', help='graphic file name; required when given (default: the device default, if present)')
parser.add_argument('--no-graphic', action='store_true', help='leave the graphic alone')
parser.add_argument('--create-listings', action='store_true',
                    help='create a missing listing from metadata.json (title, short and full description) first')
parser.add_argument('--package', help='application id (default: PLAY_PACKAGE credential)')
args = parser.parse_args()

shot_type, graphic_type, graphic_size, default_graphic = DEVICES[args.device]
if args.graphic and not graphic_type:
    raise SystemExit(f'{args.device} has no graphic image type.')
graphic_name = None if args.no_graphic else (args.graphic or default_graphic)
exact = parse_size(args.size) if args.size else None
names = args.shots.split(',') if args.shots else None
root = Path(args.dir)
if not root.is_dir():
    raise SystemExit(f'No image folder at {root}.')

PACKAGE = _play.package(args.package)
edits = _play.service().edits()
from googleapiclient.http import MediaFileUpload   # imported late so --help needs no SDK
images = edits.images()

edit_id = edits.insert(packageName=PACKAGE, body={}).execute()['id']
print(f'edit {edit_id}')
committed = False
try:
    listed = {l['language'] for l in edits.listings().list(packageName=PACKAGE, editId=edit_id).execute().get('listings', [])}
    plan = targets(root, listed, args.languages.split(',') if args.languages else None, parse_locale_map(args.locale_map))
    if not plan:
        raise SystemExit('No language selected: no folder matches a Play listing. Check --locale-map.')

    # Check every file before changing anything in the edit.
    work = []
    for locale, folder in plan:
        shots = select_shots(folder, names, exclude={graphic_name})
        for shot in shots:
            check_screenshot(shot, exact)
        graphic = folder / graphic_name if graphic_name else None
        if graphic and not graphic.is_file():
            if args.graphic:
                raise SystemExit(f'{folder} is missing {graphic_name}.')
            graphic = None
        if graphic and png_size(graphic) != graphic_size:
            raise SystemExit(f'{graphic} must be {graphic_size[0]}x{graphic_size[1]}.')
        work.append((locale, folder, shots, graphic))

    for locale, folder, shots, graphic in work:
        if locale not in listed:
            if not args.create_listings:
                raise SystemExit(f'{locale} has no Play listing yet; rerun with --create-listings to add it from metadata.json.')
            meta_file = folder / 'metadata.json'
            if not meta_file.is_file():
                raise SystemExit(f'--create-listings needs {meta_file}.')
            meta = json.loads(meta_file.read_text(encoding='utf-8'))
            if problems(meta):
                raise SystemExit(f'{meta_file}: ' + '; '.join(problems(meta)))
            edits.listings().update(packageName=PACKAGE, editId=edit_id, language=locale, body={
                'language': locale, **{f: meta[f] for f in LIMITS}}).execute()
            print(f'{locale}: created listing "{meta["title"]}"')
        before = images.list(packageName=PACKAGE, editId=edit_id, language=locale, imageType=shot_type).execute().get('images', [])
        print(f'{locale}: replacing {len(before)} {shot_type} with {len(shots)}' + (f', plus {graphic_type}' if graphic else ''))
        images.deleteall(packageName=PACKAGE, editId=edit_id, language=locale, imageType=shot_type).execute()
        for f in shots:
            images.upload(packageName=PACKAGE, editId=edit_id, language=locale, imageType=shot_type,
                          media_body=MediaFileUpload(str(f), mimetype='image/png')).execute()
            print(f'  {f.name}')
        if graphic:
            images.deleteall(packageName=PACKAGE, editId=edit_id, language=locale, imageType=graphic_type).execute()
            images.upload(packageName=PACKAGE, editId=edit_id, language=locale, imageType=graphic_type,
                          media_body=MediaFileUpload(str(graphic), mimetype='image/png')).execute()
            print(f'  {graphic.name}')
    edits.validate(packageName=PACKAGE, editId=edit_id).execute()
    print('validated')
    if not args.commit:
        raise SystemExit('\nDRY RUN. Nothing changed. Re-run with --commit.')
    edits.commit(packageName=PACKAGE, editId=edit_id, changesNotSentForReview=False).execute()
    committed = True
finally:
    if not committed:
        _play.discard(edits, PACKAGE, edit_id)


# Read the listing back rather than trusting the commit response.
def count(edit, locale, image_type):
    return len(images.list(packageName=PACKAGE, editId=edit, language=locale, imageType=image_type).execute().get('images', []))


def report(edit):
    for locale, _, shots, graphic in work:
        n = count(edit, locale, shot_type)
        extra = f', {count(edit, locale, graphic_type)} {graphic_type}' if graphic else ''
        print(f'PUBLISHED. {locale} now has {n} {shot_type}{extra}')
        if n != len(shots):
            print(f'WARNING: expected {len(shots)} {shot_type} for {locale}. Check the console.')


_play.read_back(edits, PACKAGE, report)
