# Filtering

Filtering narrows list endpoints with explicit field predicates such as
`status=active` or `created_after=2026-01-01`. Filters run before pagination so
each page contains only records matching the predicate.

Do not use filters to hide authorization failures. The API still checks the
bearer token before applying predicates.
