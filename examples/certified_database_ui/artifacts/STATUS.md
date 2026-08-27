# Certification status

Certified after changing the application to initialize SQLite in WAL mode. The first exact-source
run of that changed implementation passed the unchanged bounds and produced certificate
`afadf52df07e2d64e47e054d9f59de1500f96e3543d73bab4f761fcff6c82b69`.

The preceding rollback-journal run remains part of the engineering record: `items.insert/http`
observed 39.862 ms and certified to 51.821 ms under the unchanged 1.3 safety factor, outside the
50 ms bound. It was not retried unchanged and was not represented as certified.
