# M3R2 real evidence analysis

Source classification: `SANITIZED_REAL_REMOTE_EVIDENCE`; credentials present: false; scientific calculation performed: false.

The observed association `vini||normal` means account `vini`, no fixed partition, QoS `normal`, and scope `ACCOUNT_WIDE_ASSOCIATION`. The visible default `q1h-20p*` cross-references a policy with `Default=YES`, `State=UP`, `AllowAccounts=ALL`, `AllowQos=ALL`, `MinNodes=1`, `MaxNodes=1`, and `MaxTime=01:00:00`. For the one-node, two-minute non-scientific request, it is the unique compatible default.

V2 passed local validation, ran partially on Yoltla, obtained login evidence correctly, blocked safely, did not model account-wide associations, and submitted no job. The root cause was the previous parser requiring both account and partition before retaining a row.
