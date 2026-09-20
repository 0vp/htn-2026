# Project conventions

- Keep authored files at most 500 lines and at most eight immediate files per folder.
  Generated lockfiles, Xcode projects, build outputs and dependencies are exempt.
- Use nested folders by responsibility and keep types and interfaces explicit.
- `fe` is the React dashboard, `app` is the native SwiftUI iOS app, and `be` is the Python API.
- Dryft moved to the standalone private repository https://github.com/0vp/dryft
  at C:/Users/Qasim/Desktop/Projects/dryft. Do not recreate it inside this repository.
- Never commit credentials, recordings, datasets, model weights or local environments.
- Build or smoke-test each changed component before committing. Record actual checks
  and distinguish simulator builds from physical-device validation.
- Make focused local commits only. Do not push unless explicitly requested.

- Before changing robot hardware, transport or calibration, read
  `robot/README.md`; preserve measured facts versus hypotheses.
