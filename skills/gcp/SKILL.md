---
name: gcp
description: Use when a tool needs a Google Cloud service account (Google Play publishing, RevenueCat purchase validation, Firebase, any Google API), when checking which service account and project credentials belong to and what roles they hold, enabling an API, listing or creating service account keys, or when a Google API call fails with 403, SERVICE_DISABLED or a permission that "should" already be granted.
---

# Google Cloud: identity, APIs, service accounts

## Credentials

`cpm creds setup gcp` asks for each one:

| Name | Where to get it |
|---|---|
| `GCP_PROJECT_ID` | The project **id** (not the display name or number), top of the console. `--gcp-project` overrides per call. |
| `GCP_SERVICE_ACCOUNT_JSON` | IAM & Admin > Service accounts > the account > Keys > Add key > **JSON**. Downloaded once. `cpm creds` copies it to `~/.config/cpm/<project>/keys/` (0600). An OAuth client JSON (`"installed"`/`"web"`) looks similar and is refused. |

Tokens are signed locally (RS256) with the `cryptography` package if installed,
otherwise the `openssl` binary. No gcloud needed; if you have it, `gcloud auth
list` and `gcloud config list` answer the "which identity" question for your user.

## Commands

```bash
cpm gcp whoami                          # service account, key's home project, target project, roles held
cpm gcp whoami --offline                # key file only, no network
cpm gcp apis                            # enabled APIs
cpm gcp apis enable androidpublisher    # dry run; add --commit
cpm gcp service-accounts                # accounts in the project
cpm gcp service-accounts keys <email>   # user-managed keys and their ages
cpm gcp service-accounts key-create <email> --commit --save-as PLAY_SERVICE_ACCOUNT_JSON
```

`key-create` never prints the key. It lands in the credentials folder and, with
`--save-as`, its path is stored under that name for the tool that needs it.

## Traps

- **403 "API has not been used in project N" although it is enabled.** API enablement and quota belong to the project that **owns the service account**, not the one you are working in. `whoami` shows both. Enable the API there. The first APIs of a fresh project (Service Usage, Cloud Resource Manager) must be enabled from the console, because the account cannot call the API that would enable them.
- **Play: catalog reads work, purchase validation keeps failing.** Play Console splits a service account's access into **App permissions** (add the app) and **Account permissions** (financial data, order management). Granting only one side leaves reads green and validation red, which looks like propagation delay but never clears. Real propagation can take up to 36 hours; a missing app entry never resolves.
- **Play: the service account must be invited in Play Console** (Users and permissions), not only given IAM roles, and the Google Play Android Developer API must be on in its project.
- **Real-time notifications silently absent.** The role picker lists **Pub/Sub Lite Editor** beside **Pub/Sub Editor**; only Pub/Sub Editor (or Publisher on the topic, for the Play publisher account) works.
- **Key creation refused by policy.** `iam.disableServiceAccountKeyCreation` is on by default for newer organizations; an org admin must relax it for the project, or use keyless auth where the consumer supports it.
- **Keys pile up.** Ten user-managed keys per account is the cap. `service-accounts keys` shows ages; delete what no tool uses. A key is a long-lived password: one per consumer, never in git.
- **Changes applied to the wrong place.** Before any write with a CLI (gcloud, a database CLI, a hosting CLI), check which user and org it is logged into; a machine logged into a personal or sandbox org will happily apply migrations or roles there. `whoami` does this for the service account.
- **IAM changes are not instant.** New roles can take a few minutes; retry before rewriting anything.
