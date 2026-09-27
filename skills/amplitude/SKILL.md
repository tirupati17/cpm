---
name: amplitude
description: Use when listing or checking Amplitude Experiment feature flags, turning a flag on or off (kill switch, rollout), shipping code that is gated behind a new flag, or pulling event totals or unique users for the last N days from Amplitude Analytics.
---

# Amplitude: feature flags and event totals

## Credentials

`cpm creds setup amplitude` asks for each one and says where it lives:

| Name | Where to get it |
|---|---|
| `AMPLITUDE_API_KEY` | Settings > Projects > the project > General. Also in the app. |
| `AMPLITUDE_SECRET_KEY` | Same page. Server-side only. Used with the API key for the Dashboard REST API (`events`). |
| `AMPLITUDE_MANAGEMENT_KEY` | Optional unless you use flags. Experiment > **Management API** > create key (some org layouts put it under Settings > Organization > API keys). A different key from the two above; neither works in the other's place. |
| `AMPLITUDE_REGION` | Optional: `us` (default) or `eu`. Must match where the project lives; a mismatch fails as 401, not as a region error. |

## Commands

```bash
cpm amplitude flags [--grep text] [--all]      # key, ON/off, rollout, variants, segments, deployments
cpm amplitude flag <key> --off                 # dry run: current state and the PATCH
cpm amplitude flag <key> --on --commit         # changes `enabled` only
cpm amplitude target <key> --property beta_tester [--value true] [--remove] [--commit]
cpm amplitude target --property beta_tester    # which flags carry that segment
cpm amplitude events                           # event types with this week's totals
cpm amplitude events --event app_opened --days 30 [--metric uniques] [--daily]
```

`flag` only flips `enabled`; rollout, variants and targeting stay as they are,
and creating flags stays in the UI. It looks the key up to find the numeric id,
then patches `/api/1/flags/<id>`.

`target` gives one group a feature first: it adds a segment
`gp:<property> is <value> -> on` in front of the base rollout, named after the
property so a rerun replaces it. If the flag is off at 0% it switches it on
(nobody else is affected); if it is off with a base rollout above 0% it refuses,
because switching it on would release to that share of everyone.

## Traps

- **A targeting property has to be in the fetch.** Remote evaluation matches on
  the user properties sent with the Experiment fetch; the Analytics profile
  lags ingestion, so an app that only calls identify can miss its own segment
  for its first sessions. Put the property on the Experiment user and refetch
  when it changes.

- **A gate with no flag in the dashboard is not off, it is the code's
  fallback.** If the fallback is `true` the feature is live for everyone with no
  kill switch; if `false` it is dead for everyone. And debug builds that force
  flags on hide both cases. Create the flag in the same change that ships the
  gate, then check it here with `flags --grep`.
- **ON is not enough.** A flag reaches an app only if it is ON, rolled out above
  0% (or matched by a segment), and attached to the deployment whose key that app
  uses. `flags` marks `! no deployment` and `! 0% rollout`.
- **A kill switch should remove the gate, not only the feature.** If a flag
  turns off a paywall but the content locks read a different condition, users
  are left locked out with no way to pay.
- **Numeric companions.** A boolean "quota enabled" beside a numeric limit where
  0 means unlimited does nothing until the number is set too. Check both.
- **Changes are not instant.** Apps see a flip on their next flag fetch: local
  evaluation SDKs poll, remote evaluation often only at launch.
- **`events` returns 400 for an event name Amplitude never received**, shown as
  "no such event". Usually a typo, a renamed event on one platform only, or an
  event sent only from debug builds. Event names are a cross-platform contract.
- **Uniques do not add up.** A 30-day unique count is de-duplicated over the
  range; summing daily uniques overcounts. `events --metric uniques` prints
  Amplitude's own range figure.
- **Rate limits are tight** on smaller plans: queries run one at a time and
  429s are retried with Retry-After. Do not loop dozens of events per minute.
