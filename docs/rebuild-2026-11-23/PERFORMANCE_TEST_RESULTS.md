# Performance test results

Local gateway, private dev database (700 schools), one signed-in reader, 100 requests per row. Times in milliseconds, measured at the gateway API.

| Screen | Concurrency | p50 | p95 | Errors |
|---|---|---|---|---|
| School Profile | 1 | 11 | 32 | 0 |
| School Profile | 10 | 46 | 110 | 0 |
| Cluster Profile | 1 | 42 | 72 | 0 |
| Cluster Profile | 10 | 136 | 334 | 0 |
| Route day | 1 | 28 | 35 | 0 |
| Route day | 10 | 73 | 105 | 0 |

**This is not a load test.** No claim is made about 1,000 users. A representative test on staging-sized infrastructure and data is still required. Cluster Profile at 10 concurrent readers exceeds the 300 ms p95 target on this laptop and should be checked there.
