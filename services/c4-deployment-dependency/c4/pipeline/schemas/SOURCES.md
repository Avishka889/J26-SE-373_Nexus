# Where each schema came from

Every generated file is checked against a schema kept here, so a verdict does not
depend on a network or on a schema that changed since. Each was retrieved on
2026-09-27; the hash is of the bytes kept. A newer schema is a new file and a new
row, never an edit in place, so an old verdict can be reproduced.

| File | Checks | Source | Draft | Bytes | sha256 | Licence |
|---|---|---|---|---|---|---|
| `github-workflow.json` | `.github/workflows/*.yml` | https://www.schemastore.org/github-workflow.json | draft-07 | 118601 | `d10c9f4656e1bd5bc6727e9b35080e017dc167154726fca93da33c7a6bd1c4f3` | Apache-2.0 (SchemaStore) |
| `vercel.json` | `vercel.json` | https://openapi.vercel.sh/vercel.json, the `$schema` Vercel's documentation names | draft-04 | 422007 | `b405f65e3165bd49bb3df5102ffc8edf447c871fdd8366e4192f123dbbb83169` | not stated by Vercel |
| `render.yaml.json` | `render.yaml` | https://render.com/schema/render.yaml.json, published by Render and listed in SchemaStore's catalogue as "Render Blueprints" | 2020-12 | 45710 | `57aa0a1ff9c3b2d0fcb91b790b7b285aef6397adb0c92930e6e601054444cfe5` | not stated by Render |
| `kubernetes/v1.37.1-standalone-strict/deployment-apps-v1.json` | `k8s/deployment.yaml`, through kubeconform | https://raw.githubusercontent.com/yannh/kubernetes-json-schema/master/v1.37.1-standalone-strict/deployment-apps-v1.json | draft-07 style, generated | 717937 | `0b64451c0b8c36ea06dfebf952718810ae24a07779fb0ed2a6b03f1cc8735a54` | the repository states none GitHub recognises; generated from Kubernetes' OpenAPI document (Apache-2.0) |
| `kubernetes/v1.37.1-standalone-strict/service-v1.json` | `k8s/service.yaml`, through kubeconform | https://raw.githubusercontent.com/yannh/kubernetes-json-schema/master/v1.37.1-standalone-strict/service-v1.json | as above | 43682 | `8bf019854daed511e7c174896a898173fa65d88ec5937c687a37303d4cc9351b` | as above |
| `release.json.schema.json` | `<frontend>/public/release.json` | written here: the fingerprint's own shape | 2020-12 | | | this repository's |

Vercel's schema declares draft-04 but does not pass draft-04's own metaschema: at
`functions.*.experimentalTriggers[].retryAfterSeconds` (under `services`) it writes
`exclusiveMinimum: 0`, the numeric form draft-06 introduced, where draft-04 wants a
boolean beside `minimum`. Instances are checked by draft-04's rules, and no
generated `vercel.json` uses that property.

Kubernetes 1.37.1 was the stable release (`dl.k8s.io/release/stable.txt`) on the
day of retrieval. The plan named SchemaStore for the Render schema; SchemaStore
only lists Render's own URL, so the schema is Render's.
