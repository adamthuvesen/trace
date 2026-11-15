---
title: Release guide
summary: How a release moves from branch to tag.
aliases:
  - shipping guide
  - release runbook
status: current
as_of: 2026-11-01
---

# Release process

Releases start from a clean main branch.

## Prepare

Run the fast checks and read the changelog draft. The release owner confirms that every merged change has a changelog line, that the version number follows the compatibility policy, and that no open incident blocks the release. A release that changes persisted index data must also bump the index metadata version so that incremental builds do not reuse stale chunks.

### Version numbers

Patch releases fix defects. Minor releases add behavior.

## Publish

Tag the commit and build the wheel.

Upload the wheel after the package verification passes.
