---
name: revenuecat
description: Use when checking subscription metrics (MRR, revenue, active subscriptions, trials), looking up why a specific user does or does not have Pro, granting someone an entitlement for free (promo, support, giveaway, lifetime), listing products or offerings, or when a purchase, entitlement or webhook in RevenueCat does not behave as expected.
---

# RevenueCat: metrics, customers, promotional grants, catalogue

## Credentials

`cpm creds setup revenuecat` asks for each one and says where it lives:

| Name | Where to get it |
|---|---|
| `REVENUECAT_API_KEY` | Project settings > API keys > **+ New secret API key**, version **v2**. Give it only what the task needs: `customer_information` read (customer), `charts_metrics` read (metrics), `project_configuration` read (products, offerings, entitlements), and customer_information **write** only if you will grant. |
| `REVENUECAT_PROJECT_ID` | The `proj...` id in the dashboard URL: `app.revenuecat.com/projects/<id>/...`. |
| `REVENUECAT_V1_API_KEY` | Optional. A legacy **v1** secret key from the same page. Only a lifetime grant uses v1; without it the v2 key is tried there, and v1 may refuse it. |

Secret keys are server-side only. The public SDK keys (`appl_`, `goog_`) in the
app cannot do any of this and should never be used here.

## Commands

```bash
cpm revenuecat metrics                       # overview: MRR, 28-day revenue, active subs/trials
cpm revenuecat customer <app_user_id>        # entitlements, subscriptions, one-time purchases
cpm revenuecat products                      # every product, per app and store
cpm revenuecat offerings                     # offerings > packages > products, current marked *
cpm revenuecat grant <id> <entitlement> --duration monthly           # dry run
cpm revenuecat grant <id> <entitlement> --until 2027-01-31 --commit
cpm revenuecat grant <id> <entitlement> --duration lifetime --commit # v1
```

Every read takes `--json` for the raw response. `grant` is a dry run unless
`--commit`; it still resolves the entitlement (a read) so the dry run shows the
exact body.

**API versions.** Everything is v2 except a lifetime grant. v2's
`customers/{id}/actions/grant_entitlement` takes an `expires_at`, not a duration,
so "lifetime" has no v2 form; it goes to v1
`subscribers/{id}/entitlements/{identifier}/promotional` with `duration: lifetime`.
`--api v1|v2` forces one.

## Traps

- **"The paid user has no Pro."** App user ids are exact and case-sensitive. A
  UUID logged in upper case on one platform and lower case on another is two
  customers. Run `customer` with each spelling before anything else.
- **A grant is not a purchase.** No store transaction, no revenue, no
  INITIAL_PURCHASE webhook, and store refunds cannot remove it. Anything counting
  "paying users" from webhooks will not see grants. Revoke in the dashboard.
- **Why grants exist at all:** a store non-consumable (lifetime) cannot be priced
  at zero or carry an intro offer. A free lifetime has to be a promotional grant,
  and any endpoint that issues them must check server-side that the promo is live
  and be idempotent per user, or it is a free-Pro button.
- **Webhooks see store ids, not RevenueCat ids.** Play subscriptions arrive as
  `subscription:base-plan`, one-time products bare. Code that maps products by
  substring (monthly/yearly/lifetime) breaks the day an id is named differently;
  check `products` when adding one.
- **The current offering can be named anything.** Do not hardcode `default`.
- **No direct Google Ads integration.** RevenueCat's attribution integrations
  include Meta Ads but not Google Ads. The path is RevenueCat > Firebase / GA4
  (Measurement Protocol) > import `purchase` into Google Ads, and RevenueCat drops
  those events silently unless the app sets `$firebaseAppInstanceId` on the
  customer.
- **Test prices do not prove live prices.** A local StoreKit or sandbox fixture
  drifts from the store. Neither RevenueCat's API nor metrics give list prices;
  ask the owner or read the store console.
- **Reinstall can orphan balances.** Entitlements restore from the store, but
  anything keyed on an anonymous app user id (credits, hours) is lost if the id
  does not survive reinstall. Log users in with a stable id.
