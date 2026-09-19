# Project conventions

- Keep authored files at most 500 lines and at most eight immediate files per folder.
  Generated lockfiles, Xcode projects, build outputs and dependencies are exempt.
- Use nested folders by responsibility and keep types and interfaces explicit.
- `fe` is the React dashboard, `app` is the native SwiftUI iOS app, and `be` is the Python API.
- Preserve existing work in `dryft` and follow its own instructions when changing it.
- Never commit credentials, recordings, datasets, model weights or local environments.
- Build or smoke-test each changed component before committing. Record actual checks
  and distinguish simulator builds from physical-device validation.
