# Idempotency keys

Clients send `Idempotency-Key` on create and charge requests that might be
retried. The API stores the first successful response for 24 hours and returns
that response to later requests with the same key and payload.

Use idempotency keys when a network timeout leaves the client unsure whether the
server created the resource. Do not use them as authentication secrets.
