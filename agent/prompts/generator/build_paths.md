# Build Path Policies

Apply only the section matching `blueprint.build_plan.build_path`. The generic
policy applies only when no named section matches.

## official_image_direct

Use `blueprint.build_plan.selected_image` directly in `docker-compose.yml`.
Do not generate a Dockerfile or request build-time tool checks.

## official_image_extended

Generate a Dockerfile whose `FROM` is exactly
`blueprint.build_plan.selected_image`. Package-version checking is unnecessary
unless the Dockerfile installs a separate selected system or language package.
Check only packages added by the generated Dockerfile.

## system_package_repo

Check the blueprint-selected package name and version with
`check_package_version`, then use the package facts returned by the tool.

For historical Debian/Ubuntu versions, use a tool-provided snapshot source when
available. If no verified source is available, document the unresolved source
instead of inventing a snapshot URL or timestamp.

## custom_package_repo

Use only the custom repository supplied by the blueprint. Apply
`template_requirements.notes` as mandatory implementation constraints for this
path. If those notes name concrete database packages, signing keys, keyservers,
base-image preferences, or runtime fixes, use those exact instructions with
`blueprint.build_plan.selected_version`.

Database packages from the custom repository do not need `check_package_version`
against the base-image repositories, even when their package names come from
`template_requirements.notes`.

Use `check_package_dependencies` for packages installed from the base image's
repositories. Do not invent repository, mirror, direct-package, or signing-key
URLs beyond values supplied by `build_plan`, `template_requirements.notes`, or
tool results. If dependencies are unavailable, remove unnecessary dependencies
or select another suitable image based on tool observations.

When a dependency observation reports archived default sources and provides
`replacement_source_list` with `apt_update_options`, use those exact values
before installing base-image dependencies. Do not keep the archived image's
obsolete default sources active.

README must state that custom-repository database package/version availability
was not verified.

## language_package_repo

Check the selected package and version with `check_package_version`, then use the
package ecosystem and package facts supplied by the blueprint and tool results.

## prebuilt_binary

The selected artifact is not a base-image system package. Check base-image
dependencies and use only `blueprint.build_plan.selected_download_url` or a
verified artifact. Do not invent an artifact URL.

## source_compile

Check dependencies needed to fetch, unpack, configure, compile, link, install,
and run the source. Use `blueprint.build_plan.selected_download_url`; when it is
empty, document the unresolved source rather than inventing a URL.

## generic

Follow `blueprint.build_plan` and tool observations. Check the chosen base image
and packages installed from its repositories. Do not invent package sources or
remote URLs.
