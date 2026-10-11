---
name: appstore-release
description: Use when shipping an iOS app to App Store review (archive, upload, attach the build, write What's New, submit), updating localized descriptions, keywords or promotional text for App Store search, submitting an existing ready review basket, repricing subscriptions, intro offers or in-app purchases across territories, checking version/build numbers or review status, or troubleshooting rejected uploads.
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
cpm appstore metadata --spec listing.json    # preview localized description, keywords and promotional text
cpm appstore metadata --spec listing.json --backup before.json --commit
cpm appstore submit --version 1.2.3 --build 42          # inspect an existing ready review basket
cpm appstore submit --version 1.2.3 --build 42 --commit # submit it without rebuilding or replacing assets
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

## Localized listing text and an existing review basket

`metadata` accepts JSON with `bundleId`, `platform`, `version`, and `localizations`.
Each locale key contains any of `description`, `keywords`, `promotionalText`.
It updates only those fields on existing locales, with no fallback translation,
build attachment, image change or automatic submission. The version must be
editable or `READY_FOR_REVIEW`. `--commit` requires a fresh backup path; it saves
the original locale records, checks for concurrent text edits, and reads back
each patch. Keep the reviewed spec in the app repo and backups outside it.

For search, use relevant native-language terms and avoid repeating the app name,
keywords already in the title/subtitle, competitor brands or duplicate terms.
Use plain text descriptions with natural search phrases and accurate features.
Promotional text supports conversion; Apple says it does not affect search ranking.
Validate description at 4,000 characters, promotional text at 170 characters,
and keywords conservatively at 100 UTF-8 bytes, per the
[platform version reference](https://developer.apple.com/help/app-store-connect/reference/app-information/platform-version-information).
Apple's [product page guidance](https://developer.apple.com/app-store/product-page/)
describes keyword selection and promotional text. Do not claim measured search
volume or ranking gains without data.

When the user has already added a version for review, `submit` verifies the
explicit version and valid attached build, finds its ready basket, and refuses
extra/unrelated items. Run its dry run before `--commit`, then check `status`.
It does not create a basket, edit text, attach builds or cancel another review.

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

- **READY_FOR_REVIEW is not a submitted review.** The user may have clicked Add
  for Review without Submit. Text is still editable. Use `metadata` and then
  `submit` for a metadata-only finish; `release --replace-in-review` would cancel
  the existing basket unnecessarily.
- **GET reviewSubmissionItems/{id} returns 403.** That resource's instance
  route does not support GET. Read `/v1/reviewSubmissions/{id}/items` with
  `include=appStoreVersion` and inspect each item's relationship. Never assume
  a nonempty basket contains the intended version.

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
