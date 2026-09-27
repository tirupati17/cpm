---
name: google-ads
description: Use when checking or changing Google Ads from the terminal (campaign spend, clicks and conversions, pausing or enabling a campaign, changing a daily budget, running a GAQL query), when setting up Google Ads API access (developer token, OAuth refresh token, manager account id), when purchase conversions from a mobile app are missing or not reaching Ads, or when an Ads account is suspended for cloaking or another policy.
---

# Google Ads: campaigns, budgets, conversions

## Credentials

`cpm creds setup googleads` asks for each one; `cpm googleads auth` mints the refresh token.

| Name | Where to get it |
|---|---|
| `GOOGLE_ADS_DEVELOPER_TOKEN` | Only a **manager (MCC) account** has one: Tools > API Center. Create a free manager account and link your ad account under it if you have none. A new token is at **Test** access and only works on test accounts; apply for **Basic** (enough for your own accounts) from the same page. Google has added further tiers over time: whatever the page shows, anything short of Basic/Standard fails on a real account with `DEVELOPER_TOKEN_NOT_APPROVED`. |
| `GOOGLE_ADS_CUSTOMER_ID` | The 10-digit id top right in the Ads UI of the account to act on. Dashes optional. `cpm googleads accounts` lists what you can reach. |
| `GOOGLE_ADS_LOGIN_CUSTOMER_ID` | Optional. The manager's id, **only** when your Google user reaches the account through that manager. Wrong or missing here gives `USER_PERMISSION_DENIED`. |
| `GOOGLE_ADS_CLIENT_ID` / `_SECRET` | GCP console, any project you own: enable **Google Ads API**, configure the **OAuth consent screen** (External; add yourself under Test users), then Credentials > Create OAuth client ID > **Desktop app**. Not "Web application": the loopback redirect needs Desktop. |
| `GOOGLE_ADS_REFRESH_TOKEN` | `cpm googleads auth`. Sign in as the Google user that has access to the Ads account (not necessarily the GCP owner). Saved, never printed. |

## Commands

```bash
cpm googleads auth                                  # browser sign-in, saves the refresh token
cpm googleads accounts                              # reachable customer ids, names, manager flag
cpm googleads campaigns --days 7                    # status, budget, cost, clicks, conversions
cpm googleads conversions --days 30                 # conversion actions, imported or not, recent count
cpm googleads query "SELECT campaign.name, metrics.clicks FROM campaign WHERE segments.date DURING LAST_7_DAYS"
cpm googleads budget "<campaign name or id>" 25     # dry run; Google validates it (validateOnly)
cpm googleads pause  "<campaign>" --commit
cpm googleads enable "<campaign>" --commit
```

Every write is a dry run until `--commit`, and the dry run already asks Google to
validate it, so a green dry run proves the credentials can write. Money is in the
account currency; the API speaks micros (1,000,000 per unit). `--customer` acts on
another account. The API version is one constant in `toolkit/services/googleads/_ads.py`;
if every call returns 404, it has been sunset: set `GOOGLE_ADS_API_VERSION=vNN`.

## Traps

- **Account suspended for "Circumventing systems: cloaking" on a site that serves the same page to everyone.** A direct app download link (an `.apk`, or any install path that bypasses the store) next to the store badge on the landing page reads to the policy review as evading app-store policy. Remove every such link before appealing, and say so in the appeal. One appeal at a time: a second within about a week can be marked unfounded. Advertiser verification and "confirm your affiliation" tasks can block the appeal; finish them first. No API campaign work while suspended.
- **"Download" conversion counting every screen visit.** A GA4 event built on `screen_view` / screen class fires each time the screen opens. Installs come from the Ads **app download** conversion (store-measured, no SDK) or `first_open`, once per device.
- **Paying for purchases Ads never sees.** RevenueCat has **no direct Google Ads integration** (Meta has one, Google does not). The route is RevenueCat > Integrations > **Firebase** (server-side, GA4 Measurement Protocol; needs the Firebase app id and a Measurement Protocol API secret per platform) > GA4 > link GA4 to Ads > import `purchase` as a conversion. The app must set the Firebase app instance id on the RevenueCat customer (`$firebaseAppInstanceId`), or RevenueCat **drops every event silently**. The other route is an MMP (AppsFlyer, Adjust, ...), which on iOS brings ATT and a "tracks you" privacy answer.
- **Imported conversion shows 0 while sales happen.** Check upstream in order: event in GA4 Realtime, GA4 linked to this Ads account, action status ENABLED and primary. `cpm googleads conversions` shows type, primary and the recent count side by side.
- **Test purchases polluting the conversion Ads bids on.** Sandbox purchases are forwarded too. Keep analytics collection off in debug/simulator builds, and remember `setAnalyticsCollectionEnabled` on iOS persists across launches, so the off path must write `false` back.
- **iOS app that declares "does not track" ships an IDFA reader.** The plain `FirebaseAnalytics` SPM product embeds an IDFA support framework; `FirebaseAnalyticsCore` does not and needs no code change.
- **Refresh token dies after a week.** An OAuth consent screen left in **Testing** issues refresh tokens that expire in 7 days (`invalid_grant`). Set it to **In production** (an unverified-app warning for your own use is fine), then run `auth` again. No refresh token returned at all: revoke the app at myaccount.google.com/permissions and rerun (`auth` already forces `prompt=consent`).
- **Budget change moved other campaigns.** A shared budget belongs to several campaigns; `budget` refuses it without `--shared-ok`.
