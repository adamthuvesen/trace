# Authentication errors

HTTP 401 means the bearer token is missing, expired, or invalid. HTTP 403 means
the token is valid but lacks permission for the requested resource.

Authentication failures are not fixed by retrying. Refresh the token or ask an
administrator to grant the missing scope.
