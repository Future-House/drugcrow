#!/usr/bin/env python3

import os
from google.cloud.bigquery.client import Client

os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = '/Users/sid/.config/gcloud/application_default_credentials.json'
client = Client()

query = 'SELECT chembl_id, pref_name FROM `bigquery-public-data.ebi_chembl.molecule_dictionary` WHERE molecule_type = "Small molecule" LIMIT 10'
query_job = client.query(query) 
rows = query_job.result() 

for row in rows:
    print(row.pref_name, row.chembl_id)
