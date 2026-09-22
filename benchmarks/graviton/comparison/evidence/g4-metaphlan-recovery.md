# G4 MetaPhlAn worker recovery
All five Batch jobs used the same ECS container instance, now missing from ECS lookup. The MetaPhlAn CE Auto Scaling history records only one successful worker launch during the run: i-0d6f195921644a5d1 at 16:15:39 UTC, terminated 16:23:54 UTC. All five tasks ran within 16:17:52–16:23:01 UTC, one attempt each. Its saved Spot request confirms m8g.metal-24xl in us-east-2c. Saved Spot history shows $0.4308/hour effective from 15:00 UTC, constant throughout the task interval. This corroborates placement through CE membership and timing, rather than a surviving direct ECS→EC2 mapping.

Evidence: `g4-jobs.json`, `g4-metaphlan-spot-request.json`, and
`g4-spot-prices.json`. CloudTrail lookup was denied by the head-node IAM role;
Auto Scaling and Spot request APIs supplied the needed evidence instead. The
large raw scaling-activity dump was removed after this finding was recorded.
