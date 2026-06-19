# Retryable errors

Retry requests after HTTP 408, 429, and 503 responses. These responses mean the
server did not finish the work, is temporarily overloaded, or is asking the
client to slow down.

Use exponential backoff with jitter. Never retry 400 validation errors without
changing the request, because the same malformed payload will fail again.
