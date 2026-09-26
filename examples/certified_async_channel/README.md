# Certified asynchronous channel

This minimal example has two independently scheduled workers connected by one real
`queue.Queue[PreparedJob]`. The producer and consumer retain their actual interfaces: the consumer
poll request contains only blocking policy, while the payload appears later in `QueueTakeResponse`.

`dagcert-contract/v8` declares a `prepared-jobs` typed channel and joins the independently valid
producer and consumer expressions with `async_handoff`. Dagcert checks the payload against the
source-derived enqueue outcome and dequeue input field, checks the one-token queue resource
effects, and then applies the ordinary finite union bound over both worker-local paths.

Run:

```powershell
python -m examples.certified_async_channel.certify
```

The example deliberately makes no FIFO, infinite-liveness, or fairness claim.
