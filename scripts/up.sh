#!/usr/bin/env bash
# Build the image and bring up the local kind stack (D17).
set -euo pipefail
cd "$(dirname "$0")/.."

docker build -t contribflow:dev .
# Tag with the image ID, so every rebuild gets a new tag and Terraform reloads it into kind.
tag="$(docker image inspect contribflow:dev --format '{{.Id}}' | cut -c8-19)"
docker tag contribflow:dev "contribflow:${tag}"

terraform -chdir=deploy/terraform/local init -input=false
terraform -chdir=deploy/terraform/local apply -input=false -auto-approve -var "image_tag=${tag}"
terraform -chdir=deploy/terraform/local output
