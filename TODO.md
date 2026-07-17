# TODO list

## High priority

- Pass a "dok_target" value in the config.
  - Select questions such that the average DOK is as close as possible (but at
    least as much as) the target.
  - Report the actual average DOK and the target as part of the report.
  - If the target is impossible to achieve while satisfying the rest of the
    filter requirements, get as close as possible and highlight the actual average
    DOK in yellow in the report on the command line.
- Add ability to pass in a previous manifest and generate a new version of the
  same test (same questions, scrambled question and choice order).
- Add ability to pass in a previous manifest (or multiple manifests) and filter
  out questions that have already been used.

## Medium priority

## Low priority

- Add preamble section to the YAML to add preamble for that specific questions
  set or question.
