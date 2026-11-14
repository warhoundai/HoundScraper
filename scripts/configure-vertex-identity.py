"""Configure a keyless, repository-bound qualification identity using your own gcloud CLI.

No private key is created. This script is needed only where a connected tool cannot
create service accounts. It verifies existing resources before reusing them.
"""
import argparse,json,subprocess
p=argparse.ArgumentParser();p.add_argument('--project',required=True);p.add_argument('--repository-id',default='1457402229');p.add_argument('--owner-id',default='350209229');args=p.parse_args()
def command(*words):
    r=subprocess.run(['gcloud',*words,'--project='+args.project,'--format=json','--quiet'],capture_output=True,text=True)
    if r.returncode:raise RuntimeError(r.stderr.strip())
    return json.loads(r.stdout) if r.stdout.strip() else {}
def ensure(describe,create):
    try:return command(*describe)
    except RuntimeError as e:
        if 'NOT_FOUND' not in str(e) and 'does not exist' not in str(e):raise
        return command(*create)
project=command('projects','describe',args.project);number=project['projectNumber'];account='houndscraper-model-test@'+args.project+'.iam.gserviceaccount.com';pool='houndscraper-github';role='houndScraperModelQualification'
ensure(('iam','service-accounts','describe',account),('iam','service-accounts','create','houndscraper-model-test','--display-name=HoundScraper model test'))
custom=ensure(('iam','roles','describe',role),('iam','roles','create',role,'--title=HoundScraper model test','--permissions=aiplatform.endpoints.predict,serviceusage.services.use','--stage=GA'))
if set(custom['includedPermissions'])!={'aiplatform.endpoints.predict','serviceusage.services.use'}:raise RuntimeError('Existing role has unexpected permissions; review it before continuing')
ensure(('iam','workload-identity-pools','describe',pool,'--location=global'),('iam','workload-identity-pools','create',pool,'--location=global','--display-name=HoundScraper GitHub tests'))
condition="assertion.repository_id == '"+args.repository_id+"' && assertion.repository_owner_id == '"+args.owner_id+"' && (assertion.ref == 'refs/heads/feature/advanced-extraction' || assertion.ref == 'refs/heads/main')"
try:
    provider=command('iam','workload-identity-pools','providers','describe','github','--workload-identity-pool='+pool,'--location=global')
    if provider.get('attributeCondition')!=condition:raise RuntimeError('Existing provider has unexpected conditions; review it before continuing')
except RuntimeError as e:
    if 'NOT_FOUND' not in str(e) and 'does not exist' not in str(e):raise
    command('iam','workload-identity-pools','providers','create-oidc','github','--workload-identity-pool='+pool,'--location=global','--issuer-uri=https://token.actions.githubusercontent.com','--attribute-mapping=google.subject=assertion.sub,attribute.repository_id=assertion.repository_id','--attribute-condition='+condition)
command('projects','add-iam-policy-binding',args.project,'--member=serviceAccount:'+account,'--role=projects/'+args.project+'/roles/'+role,'--condition=None')
principal='principalSet://iam.googleapis.com/projects/'+number+'/locations/global/workloadIdentityPools/'+pool+'/attribute.repository_id/'+args.repository_id
command('iam','service-accounts','add-iam-policy-binding',account,'--role=roles/iam.workloadIdentityUser','--member='+principal)
print(json.dumps({'HOUNDSCRAPER_GCP_WIF':'projects/'+number+'/locations/global/workloadIdentityPools/'+pool+'/providers/github','HOUNDSCRAPER_GCP_SERVICE_ACCOUNT':account,'HOUNDSCRAPER_GCP_PROJECT':args.project,'HOUNDSCRAPER_GCP_MODEL':'gemini-3.8-flash'},indent=2))
