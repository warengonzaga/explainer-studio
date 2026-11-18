# Changelog

All notable changes to Explainer Studio are documented here.

This project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- delegate workspace and project creation plus media registration to AIVEE
- store Explainer workflow files in AIVEE's project namespace and resolve legacy projects from their existing root layout

## [0.1.0] - 2026-11-11

### Added

- install AIVEE with Studio and render through CLI
- add Waren sample avatar pack
- add chat-first explainer studio plugin (#1)

### Changed

- pin release-build-flow-action (#10)
- harden AIVEE rendering workflow (#8)
- use generic Engine timelines
- keep short-form content within safe zones
- initialize explainer studio
