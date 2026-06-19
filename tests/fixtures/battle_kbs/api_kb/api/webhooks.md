# Webhooks

Webhooks deliver event notifications to a customer endpoint after objects change
inside Trace. Each webhook request includes an `X-Trace-Signature` header.
Consumers verify the signature against the webhook signing secret before
trusting the event.

Webhook retries use exponential backoff when the customer endpoint returns a
temporary failure. A verified webhook is not the same thing as a bearer token.
