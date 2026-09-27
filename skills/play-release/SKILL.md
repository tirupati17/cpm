---
name: play-release
description: Use when publishing an Android app to Google Play (upload an AAB to internal, alpha, beta or production, staged rollout), when changing the Play listing text, screenshots, feature graphic or TV banner, when creating or repricing one-time in-app products, when checking what a Play track serves right now, or when Play rejects an upload, a versionCode, or an edit.
---

# Google Play: publish, listings, images, in-app products

## Credentials

`cpm creds setup play` asks for each one and says where it lives:

| Name | Where to get it |
|---|---|
| `PLAY_PACKAGE` | The app's `applicationId`, exactly. Or pass `--package`. |
| `PLAY_SERVICE_ACCOUNT_JSON` | Path to a service account key. GCP console > IAM > Service accounts > create one > Keys > Add key > JSON. `cpm creds` copies it into `~/.config/cpm/<project>/keys/`. |

Before the key works:

1. Enable the **Google Play Android Developer API** on that GCP project (APIs & Services > Library).
2. Play Console > **Users and permissions** > Invite new user > the service account's email.
3. Grant **App permissions** for this app (release to production/testing, manage store listing, manage in-app products), not only Account permissions. With account-level rights alone it reads the catalogue happily and then fails on anything that touches a release.
4. The app must already exist in Play Console, and its very first AAB must be uploaded by hand; the API cannot create an app.

Environment variables of the same names win over the store (CI). Needs
`pip install google-api-python-client google-auth` in the Python that runs `cpm`;
`--help` and every local check work without it.

## Commands

Every command that changes Play is a **dry run unless `--commit`**. The dry run
does the real work (upload, set, ask Play to validate the edit) and then deletes
the edit, so what you rehearse is what will happen. After a commit each command
reads the live state back instead of trusting the response.

```bash
cpm play status                                   # what every track serves (read only)
cpm play stage                                    # copy the built AAB/APK to artifacts/<version>/ + release.json
cpm play publish production                       # rehearse
cpm play publish production --rollout 20 --commit # staged rollout
cpm play publish internal --commit
cpm play listing [--languages en-US] [--create] [--forbid-dashes] [--commit]
cpm play images --dir store-images [--commit]                       # phone screenshots + feature graphic
cpm play images --device tv --dir play-assets/tv --size 1920x1080 [--commit]
cpm play products --spec play-products.json [--commit]
```

Paths default to the git toplevel of the current directory (`--repo` to override):
version from `app/build.gradle(.kts)` (`--gradle`), bundle from
`artifacts/<version>/release.json` (`--artifacts`), notes from
`release-notes/<version>/<play-language>.txt` (`--notes`), listing copy from
`store-listing/<play-language>.json`. `cpm play <command> --help` has the rest,
including the image folder layouts and the product spec format.

## Order

1. Bump `versionCode` and `versionName` in the app's build file. Literal values only.
2. Write `release-notes/<version>/en-US.txt` (plus other languages). Users read these: no flag names, no internals, at most 500 characters each.
3. Build and verify the signed AAB (signer certificate, target SDK, whatever the store requires), then stage it: your build script writes `release.json`, or run `cpm play stage`.
4. `cpm play status`, then `cpm play publish <track>` (dry run). Read what it says it is replacing.
5. `cpm play publish <track> --commit`. For production prefer `--rollout 10`/`20` first, then publish again at 100 once vitals look clean.

## Traps

- **An old bundle ships and every log looks right.** `artifacts/<version>/` survives a failed build. `publish` rehashes the AAB against `release.json` and checks it against the build file's version; never hand-edit `release.json` to get past that. Check timestamps too, and make sure the build script actually ran (a non-executable script exits 126 and leaves last run's files looking new; call it with `bash`).
- **A staged rollout quietly becomes 100%.** Only rollout 100 is `completed`; anything less is `inProgress` with `userFraction`. Play rejects `userFraction` on a completed release.
- **"versionCode already used".** A versionCode that was ever uploaded cannot be reused, even if never released. Bump it. `publish` reuses a bundle already in Play's library only when its sha256 matches `release.json`; the same number with different bytes is refused.
- **"You must let us know whether your app uses any Foreground Service permissions."** Play refuses every release edit until App content > Foreground service permissions covers each `FOREGROUND_SERVICE_*` type in the bundle, and that form only lists types it has seen in an uploaded bundle. First release with a new type: upload the bundle in an edit with no track change and commit it, fill the form (description plus a video per type), then publish; the library reuse above means no versionCode bump.
- **"This release no longer supports N devices."** A dependency's manifest merged in permissions that imply required hardware (camera, Bluetooth, media projection). Remove unused ones with `tools:node="remove"` and declare hardware `required="false"`; diff `aapt2 dump badging` of the previous and new APK whenever a native SDK arrives.
- **Build config keys missing from a local release build.** Values read from `local.properties`/env compile to empty strings and silently switch features off in production (push, analytics). Make the release build refuse to run without each one.
- **Release notes rejected mid-edit.** Over 500 characters per language, or an empty file. Checked locally before any network call.
- **Listing text.** Title 30, short 80, full 4000 characters. No ranking or price words ("best", "#1", "top", "free", "new", "sale") in the title, no emoji, no all-caps words. Play ranks title > short > full description and indexes the full one: search phrase in the title, repeat core terms naturally in the full description, never a keyword list. Changes take hours to show in search.
- **Screenshots.** At most 8 per device type (more is refused, not truncated; choose the story with `--shots`). 24-bit PNG without alpha. Feature graphic 1024x500, TV banner 1280x720. Only languages that already have a listing are touched; `--create-listings` adds one from a reviewed `metadata.json`. Adding the TV or Wear form factor and sending it for review are Console steps, not API calls.
- **In-app product ids are a contract** with whatever grants the purchase (the app, a billing backend like RevenueCat). Change them there first. Consumable vs non-consumable is not a Play setting for one-time products: the app or backend consumes the purchase.
- **Regional prices.** Give a USD base; Play converts it per region. Hand-set a region (`"IN": "24 INR"`) when conversion lands on an odd number; use a region group at a lower USD price for lower-income economies. A stale `regionsVersion` is only named in the error; `products` retries once with the version Play asks for.
- **Abandoned edits.** Every uncommitted edit (dry run, rejected upload, Ctrl-C) is deleted in a `finally`. If a command dies harder than that, the edit expires on its own; it does not block the next one.
