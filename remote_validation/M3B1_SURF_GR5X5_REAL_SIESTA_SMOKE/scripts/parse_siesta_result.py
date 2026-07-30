#!/usr/bin/env python3
import argparse,hashlib,json,re,sys
from pathlib import Path
parser=argparse.ArgumentParser(); parser.add_argument('--package-root',type=Path,required=True); args=parser.parse_args()
root=args.package_root.resolve(); sys.path.insert(0,str(root/'scripts/runtime_parser'))
from siestaflow.engines.siesta.output_parser import SiestaOutputParser
from siestaflow.engines.siesta.models import OutputClassification
manifest=json.loads((root/'package_manifest.json').read_text())
stdout=(root/'results/siesta.out').read_text(errors='replace'); stderr=(root/'results/siesta.err').read_text(errors='replace')
record=SiestaOutputParser().parse((stdout+'\n'+stderr).splitlines(True))
execution=json.loads((root/'evidence/execution/summary.json').read_text())
accounting=json.loads((root/'evidence/accounting/summary.json').read_text())
raw=stdout+'\n'+stderr; state=str(accounting.get('state') or '').upper()
if record.normal_termination and record.scf_converged: termination='NORMAL_CONVERGED_TERMINATION'
elif record.normal_termination: termination='NORMAL_NONCONVERGED_TERMINATION'
elif record.classification is OutputClassification.INPUT_ERROR: termination='INPUT_FAILURE'
elif record.classification is OutputClassification.PSEUDOPOTENTIAL_ERROR: termination='PSEUDOPOTENTIAL_FAILURE'
elif re.search(r'\b(?:MPI_ABORT|srun: error|PMI error|MPI failure)\b',raw,re.I): termination='MPI_FAILURE'
elif re.search(r'(?:no space left|read-only file system|permission denied|I/O error)',raw,re.I): termination='FILESYSTEM_FAILURE'
elif state.startswith('TIMEOUT') or record.classification is OutputClassification.TIMEOUT: termination='TIME_LIMIT'
else: termination='UNKNOWN_FAILURE'
def hash_ok(key):
 item=manifest[key]; return hashlib.sha256((root/item['packaged_path']).read_bytes()).hexdigest()==item['packaged_sha256']
summary={'job_id':execution.get('job_id') or accounting.get('job_id'),'siesta_exit_code':execution.get('exit_code'),'sacct_state':accounting.get('state'),'sacct_exit_code':accounting.get('exit_code'),'normal_termination':record.normal_termination,'termination_class':termination,'scf_started':record.scf_started,'scf_converged':record.scf_converged,'scf_iterations':record.scf_iterations,'number_of_atoms':record.atoms or manifest['calculation']['number_of_atoms'],'number_of_species':record.species or manifest['calculation']['number_of_species'],'species':manifest['calculation']['species'],'geometry_hash_verified':hash_ok('geometry'),'fdf_hash_verified':hash_ok('fdf'),'pseudo_hash_verified':hash_ok('pseudopotential'),'NaN_detected':bool(re.search(r'\bnan\b',raw,re.I)),'MPI_failure_detected':termination=='MPI_FAILURE','filesystem_failure_detected':termination=='FILESYSTEM_FAILURE','scientific_interpretation_allowed':False,'parser':'SiestaOutputParser','parser_classification':record.classification.value}
target=root/'evidence/result_summary.json'; target.write_text(json.dumps(summary,sort_keys=True,indent=2)+'\n')
print('REAL_SIESTA_OUTPUT_PARSER_PASS')
