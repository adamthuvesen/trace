# Pagination

List endpoints return `next_page_token` when more records are available. Send
that token as `page_token` on the next request to continue from the previous
position.

Cursor pagination is stable during inserts because the token represents an
ordered position, not a page number.
