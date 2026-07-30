#!/usr/bin/env python3
import json,sys
from pathlib import Path
from siestaflow.execution.allocation_controller import AllocationController,ExecutionStatus
campaign=Path(sys.argv[1]); root=Path(sys.argv[2])
controller=AllocationController.from_file(campaign,root=root)
status=controller.run()
print(json.dumps({'campaign_id':controller.config.campaign_id,'job_id':controller.slurm.job_id,'status':status.value,'summary':str(controller.summary_path),'login_node_persistent_process_required':False},sort_keys=True))
raise SystemExit(0 if status is ExecutionStatus.COMPLETED else 2)
