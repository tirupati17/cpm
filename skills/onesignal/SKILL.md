---
name: onesignal
description: Use when sending a push notification to a specific user, a list of users, a segment or everyone; when checking how many devices can receive push or whether iOS/Android push is configured; when reviewing recent sends and their delivery counts; or when a push "was sent" but never arrived.
---

# OneSignal: push to users or segments, delivery, app setup

## Credentials

`cpm creds setup onesignal` asks for each one and says where it lives:

| Name | Where to get it |
|---|---|
| `ONESIGNAL_APP_ID` | Dashboard > the app > Settings > **Keys & IDs**. Not a secret; it is in the app too. |
| `ONESIGNAL_REST_API_KEY` | Same page, **App API key**. Server-side only. Keys starting `os_v2_` are sent as `Authorization: Key ...`, older ones as `Basic ...`; set `ONESIGNAL_AUTH_SCHEME` to override. |
| `ONESIGNAL_ORG_API_KEY` | Optional. Organization > **Keys & IDs** (the organization / User Auth key). Only `cpm onesignal app` needs it. |

## Commands

```bash
cpm onesignal send --external-id <uid> --title "Hi" --body "Text"         # dry run: prints the body
cpm onesignal send --external-id <a>,<b> --body "Text" --url myapp://x --commit
cpm onesignal send --segment "Total Subscriptions" --body "Text" --commit
cpm onesignal send --subscription <id> --body "Test" --data kind=test --commit
cpm onesignal notifications --limit 20 [--kind api]   # sent / failed / errored / clicked
cpm onesignal app                                    # counts + is APNs / FCM configured
```

`send` is a dry run unless `--commit`, picks exactly one audience, splits
external_id lists into requests of 2,000, and adds an `idempotency_key` so an
accidental resend is dropped. Send to your own test device (`--subscription`)
before a segment.

## Traps

- **"Sent" but nothing arrived: no external_id on the device.** Targeting by
  `external_id` only reaches devices whose app called `OneSignal.login(<id>)` with
  that exact string. If one platform never calls `login`, its users cannot be
  targeted at all. Check the user in Audience > Subscriptions.
- **Aliases are case-sensitive.** A UUID logged in as `ABC...` on one platform
  and looked up as `abc...` by the server never matches. Normalise (lower case)
  on every side, then ship a build so devices re-register.
- **One id per install is not one id per person.** If the id you log in with is
  an anonymous per-install id, a second phone is a different user and will never
  get that person's push. Link devices with a real account first.
- **HTTP 200 is not delivery.** When nobody matches, OneSignal answers 200 with
  an empty `id` and `errors` such as "All included players are not subscribed".
  `send` treats that as failure (exit 2). Code that only checks `res.ok` reports
  success on every one of these.
- **A release built without the app id ships silently.** If the app id comes
  from a local, untracked file, a build from a machine without it registers no
  device and nothing errors. Make the release script refuse to build when the
  id is empty, and confirm new devices appear after a release.
- **Android needs FCM configured on the OneSignal app** (Settings > Push >
  Google Android). Without it Android devices do not subscribe. `app` shows
  whether APNs and FCM are set.
- **`failed` vs `errored` in `notifications`.** Failed is dead tokens
  (uninstalls), expected to creep up. Errored is the platform refusing the send,
  usually an expired APNs key or FCM credential: fix it the day it appears.
- **Server-side keys stay server-side.** The REST key can message every user.
  Never put it in an app, a client bundle or a public repo.
