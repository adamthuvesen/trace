# Batch imports

Batch imports accept a CSV upload, validate every row, and create records only
after the validation phase succeeds. Failed rows are reported with row numbers
and field names.

Large imports should use idempotency keys so a client can retry safely after a
timeout. Imports are asynchronous and should be polled with the job status API.
