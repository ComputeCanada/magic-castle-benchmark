#/bin/bash

FILENAME="./output.txt"

# Remove color
cat $FILENAME | grep timestamp | sed -e 's/\x1b\[[0-9;]*m//g' >/tmp/log

# Force mapping for run_id in case the index is new
curl -X PUT \
  -H "CF-Access-Client-Id: ${OPENSEARCH_CF_CLIENT}" -H "CF-Access-Client-Secret: ${OPENSEARCH_CF_SECRET}" -H 'Content-Type: application/json' \
  -u "${OPENSEARCH_USERNAME}:${OPENSEARCH_PASSWORD}" "${OPENSEARCH_URL}/${OPENSEARCH_INDEX}" -d '
{
  "mappings": {
    "properties":{
      "run_id":{ "type": "keyword" },
      "workspace":{ "type": "keyword" },
      "program":{ "type": "keyword" },
      "host":{ "type": "keyword" }
    }
  }
}
'

while IFS= read -r line; do
  echo "{\"create\" : {}}"
  echo "${line}"
done < <(jq -c "del(.hook) | del(.outputs) | . + { \"run_id\": \"${RUN_ID}\", \"workspace\": \"${TF_WORKSPACE}\", \"program\":\"terraform\" }" /tmp/log) > /tmp/to_elastic-data

curl -X POST \
    -H "CF-Access-Client-Id: ${OPENSEARCH_CF_CLIENT}" -H "CF-Access-Client-Secret: ${OPENSEARCH_CF_SECRET}" -H 'Content-Type: application/json' \
    -u "${OPENSEARCH_USERNAME}:${OPENSEARCH_PASSWORD}" "${OPENSEARCH_URL}/${OPENSEARCH_INDEX}/_bulk" --data-binary @/tmp/to_elastic-data