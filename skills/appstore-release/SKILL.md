---
name: appstore-release
description: Use when shipping an iOS app to App Store review (archive, upload, attach the build, write What's New, submit), when repricing subscriptions, intro offers or in-app purchases across territories, when asked for the next build number or the app's marketing version, when an upload is rejected as a duplicate build or for a mismatched extension version, or to check what is in review right now.
---

# App Store Connect: archive, upload, submit

## Credentials

`cpm creds setup appstore` asks for each one and says where it lives:

| Name | Where to get it |
|---|---|
| `ASC_BUNDLE_ID` | The app target's bundle id, exactly (capitals matter). Or pass `--bundle-id`. |
| `ASC_KEY_ID` | App Store Connect > Users and Access > Integrations > **Team Keys**. Create one with the **Admin** or **App Manager** role (Developer cannot create versions or submit). |
| `ASC_ISSUER_ID` | Shown above the key list on the same page. One per team. |
| `ASC_KEY_PATH` | The `AuthKey_<id>.p8`. Apple lets you download it **once**, at creation. Lost it: revoke and make a new key. `cpm creds` copies it into `~/.config/cpm/<project>/keys/`. |
| `ASC_TEAM_ID` | Optional. Only asked when the app target has no `DEVELOPMENT_TEAM`. |

Environment variables of the same names win over the store (CI). Needs
`pip3 install 'pyjwt[crypto]' certifi` in the Python that runs `cpm`.

## Commands

```bash
cpm appstore status                           # versions + states, open submissions, recent builds (read-only)
cpm appstore version                          # app target's MARKETING_VERSION (offline)
cpm appstore build-number                     # highest uploaded build + 1
cpm appstore release                          # dry run: checks + plan, changes nothing
cpm appstore release --commit                 # archive, upload, wait, attach, What's New, submit
cpm appstore release --commit --replace-in-review   # cancel what is in review, ship this instead
cpm appstore release --commit --archive <path>.xcarchive   # reuse an archive (after a timeout)
cpm appstore release --commit --skip-upload   # already uploaded: wait, attach, submit
cpm appstore release --commit --no-submit     # stop after attaching; submit by hand
cpm appstore release --commit --testflight    # archive + upload only: a TestFlight build, even while a version is in review
cpm appstore prices --spec ladder.json [--out ios.json] [--markdown table.md] [--commit]   # reprice from a spec
```

Discovered, overridable: `--repo` (git toplevel), `--workspace`/`--xcodeproj`
(the only one; not `--project`, which `cpm` reads as the credentials project), `--scheme` (named after the project, or the only shared one),
`--team-id` (the app target's `DEVELOPMENT_TEAM`), `--notes-dir`
(`<repo>/release-notes`), `--build-dir` (`<tmp>/cpm-appstore/<scheme>`).
`--no-em-dash` refuses What's New containing an em dash (house style).

## Order

1. Bump `MARKETING_VERSION` on the app target in Xcode. That is the only place.
2. Write `release-notes/<version>/en-US.txt` (required, the fallback for every
   store locale) plus `<locale>.txt` or `<language>.txt` for others. Max 4000
   characters each; user-facing words, no internals.
3. `cpm appstore release` and read the plan: version, build, scheme, team, which
   store version it will reuse, rename or create.
4. `cpm appstore release --commit`. Processing takes 5 to 45 minutes; it waits.
5. `cpm appstore status` to confirm `WAITING_FOR_REVIEW`.

Never run `--commit` on an agent's own initiative: it builds, uploads and submits.

## Repricing (`prices`)

The spec (format in `toolkit/services/appstore/_prices.py`) names a base price in
one territory that Apple's equalizations carry everywhere else, hand-set
territories, an optional intro offer (exact prices, or the point nearest a fraction
of the list price, with a discount range to flag), an optional instalment plan, and
in-app purchase schedules. The dry run reads every price point it needs (a full
fraction-of-list run takes about two minutes) and prints the point each territory
gets; `--out` saves them for `cpm play prices --match`.

- **One intro offer per territory.** Apple refuses an overlapping one, so `--commit`
  tries the new offer first and deletes the old one only when the create is refused,
  then creates again at once; a second failure restores the old offer.
- **Existing subscribers.** `preserveCurrentPrice: true` keeps them on their price.
- **Instalment plans.** A yearly can carry a MONTHLY plan type (pay monthly for a
  year). Its prices and intro offers are separate records (`planType`); repricing
  only the up-front plan leaves the instalment one at the old price.
- **IAP schedules.** One POST replaces the whole schedule: name every manual
  price; the rest become automatic from the base territory.

## Traps

- **Upload rejected as a duplicate, after a full archive.** The project pins
  `CURRENT_PROJECT_VERSION` and nothing bumps it; or a local counter or CI run
  number drifted from what Apple accepted. Ask App Store Connect
  (`build-number`); never count. Sort builds numerically: the API's `version`
  is a string, so 9 sorts after 100.
- **Processing fails over an extension's version.** Widgets, watch apps and
  notification extensions drift (app 1.0.96, widget 1.0.7) and Apple requires
  every embedded bundle to match the app. `release` forces `MARKETING_VERSION`
  and the build number onto every target at archive time. When reading the
  version, match the bundle id with its trailing `;`, or `com.x.App` also hits
  `com.x.App.Widget` and returns the stale number.
- **Re-run uploads the same build twice.** A build still processing is invisible
  to the builds API. Apple's "redundant binary" / "already been used" rejection
  means the first upload landed; `release` treats it as success and waits.
- **Store version string drifts from the binary** (store 1.0.70 carrying build
  1.0.106). `release` renames the editable store version to the marketing version.
- **A version already in review blocks the release.** Without
  `--replace-in-review` it stops and says so. With it, the review submission is
  cancelled (the queue position is lost) and the version becomes editable
  asynchronously, so it polls before reusing it.
- **Export-compliance prompt stalls processing.** Set
  `INFOPLIST_KEY_ITSAppUsesNonExemptEncryption = NO` on the app target when the
  app only uses exempt encryption (HTTPS), and it never asks.
- **Codesign fails with odd xattr errors.** Derived data inside an iCloud-synced
  folder picks up file-provider attributes. The build dir defaults to the temp
  dir for that reason; keep it off iCloud.
- **Archive exits 65 with nothing useful.** The SDK is older than the APIs the
  app uses (availability checks do not help when symbols are missing from the
  SDK). The archive log is filtered to `error:` lines; check `xcodebuild -version`.
- **Token rejected.** ES256 JWT, `aud` `appstoreconnect-v1`, header `kid` =
  key id, lifetime at most 20 minutes, clock in sync.
- **CI cannot `pip install`** on macOS runners (PEP 668, Homebrew Python). Use a
  venv, not `--break-system-packages`.
- **Upload log warns about missing dSYMs** for a prebuilt binary framework. Often
  harmless and not fixable on your side; the build still processes.
