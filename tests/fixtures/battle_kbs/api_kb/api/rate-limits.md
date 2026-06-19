# Rate limits

The API returns HTTP 429 when a workspace exceeds the burst or sustained request
limit. Clients should read the `Retry-After` header, pause new requests, and
resume with exponential backoff.

Rate limits protect shared service capacity. They are not authorization errors
and they are not webhook delivery failures.
