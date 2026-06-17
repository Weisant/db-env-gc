# ReAct Tool Policy

Return exactly one action per response: `check_image_ref`, `check_package_version`,
`check_package_dependencies`, `check_download_url`, or `final`.

Use exactly one of these JSON shapes:

```json
{
  "action": "check_image_ref",
  "image_ref": "repository:tag",
  "reason": "why this base image fits the Dockerfile"
}
```

```json
{
  "action": "check_package_version",
  "image_ref": "repository:tag",
  "package_name": "package to install, or empty string",
  "version": "package version to install, or empty string",
  "reason": "why this package-source check is needed"
}
```

```json
{
  "action": "check_package_dependencies",
  "image_ref": "repository:tag",
  "dependencies": [
    {
      "package_name": "package to install",
      "version": "optional exact version",
      "required": true,
      "purpose": "why it is needed"
    }
  ],
  "reason": "why these dependencies are needed"
}
```

```json
{
  "action": "check_download_url",
  "url": "https://example.com/artifact.tar.gz",
  "reason": "why this generator-introduced build URL is needed"
}
```

```json
{
  "action": "final",
  "project": {
    "project_name": "string",
    "cve_id": "CVE-YYYY-NNNN or empty string",
    "files": [],
    "run_instructions": [],
    "summary": "string"
  }
}
```

Choose the next action from the blueprint and previous tool observations. Use
tool results exactly and do not repeat an identical failed request unless new
evidence materially changes the decision.

Before returning `final`:

* every Dockerfile `FROM` image must have a successful `check_image_ref`;
* required packages installed from base-image repositories must be covered by
  `check_package_dependencies`;
* selected system or language packages must be checked with
  `check_package_version` when applicable;
* for `custom_package_repo`, database packages installed from the custom
  repository may come from `template_requirements.notes` and must not be checked
  as base-image repository packages;
* generator-introduced build URLs must be blueprint-authorized, tool-authorized,
  or successfully checked;
* the project must preserve the blueprint build path and authoritative values.

If the runtime requests an incomplete best-effort project after the ReAct limit,
preserve verified choices, remove known failed URLs, and document unresolved
parts in README.
