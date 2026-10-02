#!/usr/bin/env bash
# Delete the local kind cluster and everything in it.
set -euo pipefail
cd "$(dirname "$0")/.."
terraform -chdir=deploy/terraform/local destroy -input=false -auto-approve -var "image_tag=unused"
