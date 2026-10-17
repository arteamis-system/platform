# Cost model

Researched 2026-10-17 for Singapore, USD list rates, excluding taxes/support/discounts. [Captured AWS offer rows](prices-2026-10-17.json) identify SKU, unit, tier and official source URL. Refresh prices before approval. These are estimates, not measured Arteamis bills. Shared account free tiers may already be consumed.

| Item | List rate / assumption |
| --- | --- |
| Linux `m6i.large`, On-Demand | $0.120/hour, 2 vCPU and 8 GiB |
| Dynamic public IPv4 | $0.005/hour while allocated |
| gp3 root disk | $0.096/GiB-month; 100 GiB for each live VM, default included IOPS/throughput |
| Standard EBS snapshot | $0.050/GiB-month of stored blocks; estimate 15–30 GiB per baked image, keep two |
| Lambda x86 | $0.0000166667/GB-second, plus $0.20/million requests |
| DynamoDB standard On-Demand | $0.71/million writes and $0.1425/million strongly consistent reads (up to 1/4 KiB respectively); $0.285/GiB-month after first 25 GiB; PITR $0.228/GiB-month |
| CloudWatch | $0.30/custom metric-month; $0.10/standard alarm-month; $0.70/GiB log ingestion and $0.03/GiB-month retained logs |
| S3 Standard | $0.025/GiB-month first tier, $0.005/1,000 PUT and $0.0004/1,000 GET |
| EventBridge Scheduler | $1/million invocations beyond 14 million monthly free invocations |
| Internet egress | $0.120/GiB first paid tier beyond account-wide global free allowance; downloads are ingress |
| SNS email | First 1,000/month free; then $2/100,000 deliveries; ordinary SNS request/transfer charges also apply |

Sources: AWS [EC2](https://aws.amazon.com/ec2/pricing/on-demand/), [VPC/IPv4](https://aws.amazon.com/vpc/pricing/), [EBS](https://aws.amazon.com/ebs/pricing/), [Lambda](https://aws.amazon.com/lambda/pricing/), [DynamoDB](https://aws.amazon.com/dynamodb/pricing/), [CloudWatch](https://aws.amazon.com/cloudwatch/pricing/), [S3](https://aws.amazon.com/s3/pricing/), [Scheduler](https://aws.amazon.com/eventbridge/pricing/) and [SNS](https://aws.amazon.com/sns/pricing/). Instance billing is per second with a 60-second minimum; allow for EBS/IP allocation through shutdown and deletion, and failed boots. The primary offer files are linked in the captured JSON rather than relying on third-party price summaries.

Using a 730-hour month, live compute + IPv4 + root disk is approximately:

```text
0.120 + 0.005 + (100 × 0.096 / 730) = $0.13815 per VM-hour
                                      $0.002303 per VM-minute
```

A 10-minute job with a **budgeted** 2-minute boot/registration/shutdown overhead costs about **$0.0276** before controller, snapshots, transfer and logs. GOL measured around one minute to job start in its own region; that is not an Arteamis measurement. Record real startup/tail times and retries during qualification. Two equal jobs cost roughly the same compute sequentially or in parallel; concurrency changes elapsed time and memory pressure, while repeated downloads and failed boots add cost. Two runners left until the 90-minute deadline cost roughly $0.414 plus cleanup latency. The two-attempt bound limits failed boot revisions; it is not a daily monetary cap.

With no jobs, VM, live EBS and public IPv4 counts return to zero. Remaining monthly infrastructure is approximately **$4–9**, before shared free tiers:

- Two AMI snapshots, 30–60 GiB stored total: $1.50–3.00. Snapshot size is stored blocks, not the root disk's provisioned size; inspect actual billed usage. A 30-minute image bake adds about $0.065 including its 30 GiB builder disk and IP. Longer bakes/failed attempts cost more.
- 43,200 controller invocations/month at 256 MiB and an assumed 5–20 seconds average: $0.90–3.60. Another 43,200 reaper calls at 128 MiB and 0.5 seconds average add about $0.045. Requests add about $0.017. Free Lambda allowances can reduce this, but are not reserved for Arteamis.
- Roughly 0.5–1 million small consistent DynamoDB reads plus 0.1 million writes: $0.14–0.22, plus small table/PITR storage. Metadata, retry tombstones and queue revisions grow with work and are retained for safety. Measure item sizes and tick requests; no whole-table scans are needed.
- Three custom metrics and five standard alarms: $1.40 before applicable shared allowances. At 0.1 GiB logs/month, ingestion is $0.07 plus small 14-day retained storage. GitHub holds job logs; full VM diagnostic export is not implemented. A failed boot can therefore require SSM/EC2 diagnosis before termination.
- S3 controller bundles normally well below 1 GiB: around $0.025 plus requests, bounded by 90-day object and 14-day old-version retention. Schedules total about 86,400 invocations/month, well below Scheduler's published free allowance. Without that allowance their rate is about $0.086/month. Standard SSM SecureString parameters use the AWS-managed SSM key; no dedicated monthly KMS key or interface endpoints are provisioned.

At 100 ten-minute jobs/month with 2 minutes overhead each, live runner charges are about **$2.76**, plus $4–9 baseline and transfer. Budget around **$8–13/month** if paid outbound data is 10 GiB ($1.20). At 1,000 such jobs, runner charges are about **$27.63**, then baseline and transfer. Image/cache uploads to GHCR, artifact uploads and cross-region services can dominate: an additional paid 100 GiB outbound costs about **$12**. Do not assume the shared 100 GiB internet allowance is available. Same-region S3 transfer and regional AWS routing have different transfer rules; measure the actual paths. GitHub's own artifact/storage allowances remain separate.

The initial **$20/month tag-filtered alert budget** is suitable for a low-duty fallback pilot, not a guarantee or a spending stop. Activate `ArteamisCiPool` for cost allocation and inspect allocated and unallocated account costs; some shared request/transfer costs may not carry a resource tag. Avoid dedicated NAT gateways, Elastic IPs, persistent runner volumes, warm pools and commitments. Retain On-Demand for the first qualification and any deployments. A future Spot-only CI class would need interruption handling and separate labels/admission; theoretical per-hour savings do not justify adding it before measuring startup, retry and cleanup costs.
